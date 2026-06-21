// =============================================================================
// Vue 3 Config App — 配置管理界面（主内容区）
// =============================================================================

const { createApp, reactive, ref, computed, onMounted } = Vue;

// =============================================================================
// Helpers
// =============================================================================

function getVal(obj, path) {
  return path.split('.').reduce((o, k) => (o && o[k] !== undefined) ? o[k] : undefined, obj);
}

function setVal(obj, path, value) {
  const keys = path.split('.');
  let cur = obj;
  for (let i = 0; i < keys.length - 1; i++) {
    if (cur[keys[i]] === undefined || cur[keys[i]] === null || typeof cur[keys[i]] !== 'object') {
      cur[keys[i]] = {};
    }
    cur = cur[keys[i]];
  }
  cur[keys[keys.length - 1]] = value;
}

// =============================================================================
// 全局 currentSection（与侧边栏原生 JS 共享）
// =============================================================================

window.currentSectionRef = ref('app');

// =============================================================================
// Vue App
// =============================================================================

const app = createApp({
  setup() {
    // --- State ---
    const currentSection = window.currentSectionRef;
    const configData = reactive({});
    const envHints = ref({});
    const sensitiveFields = ref([]);
    const optionsData = ref({});
    const saving = ref(false);
    const toast = ref(null);

    // --- Computed ---
    const section = computed(() => SECTIONS[currentSection.value] || { title: '', cards: [] });

    // --- Toast ---
    function showToast(msg, type = 'info') {
      toast.value = { msg, type };
      setTimeout(() => { toast.value = null; }, 3000);
    }

    // --- Field update handler ---
    function onFieldUpdate(path, value) {
      setVal(configData, path, value);
    }

    // --- API ---
    async function fetchAll() {
      try {
        const data = await ConfigAPI.fetchAll();
        Object.keys(configData).forEach(k => delete configData[k]);
        Object.assign(configData, data.configData);
        envHints.value = data.envHints;
        sensitiveFields.value = data.sensitiveFields;
        optionsData.value = data.optionsData;
      } catch (e) {
        showToast('加载配置失败: ' + e.message, 'error');
      }
    }

    // --- Data collection for save ---
    function collectData() {
      const sec = SECTIONS[currentSection.value];
      if (!sec) return {};
      const data = {};
      for (const card of sec.cards) {
        for (const field of card.fields) {
          if (field.type === 'sensitive') continue;
          const val = getVal(configData, field.path);
          // number 字段空值不发送，避免覆盖服务端默认值
          if (field.type === 'number' && (val === '' || val === null || val === undefined)) continue;
          setVal(data, field.path, val);
        }
      }
      return data[currentSection.value] || data;
    }

    async function saveSection() {
      saving.value = true;
      try {
        const body = collectData();
        const result = await ConfigAPI.save(currentSection.value, body);
        showToast(`保存成功: ${result.updated_fields?.join(', ') || '无变更'}`, 'success');
        await fetchAll();
      } catch (e) {
        showToast(e.message, 'error');
      } finally {
        saving.value = false;
      }
    }

    // --- Init ---
    onMounted(async () => {
      await fetchAll();
    });

    return {
      currentSection, configData, envHints, sensitiveFields, optionsData,
      saving, toast, section,
      onFieldUpdate, saveSection,
    };
  },
});

// =============================================================================
// Field Component
// =============================================================================

app.component('config-field', {
  props: ['field', 'configData', 'envHints', 'optionsData'],
  emits: ['update'],
  template: `
    <div class="field-group" v-show="visible">
      <label class="field-label">{{ field.label }}</label>
      <div v-if="field.desc" class="field-desc">{{ field.desc }}</div>

      <!-- Sensitive -->
      <template v-if="field.type === 'sensitive'">
        <div class="sensitive-field">
          <input type="text" :value="currentVal || '***未设置***'"
                 readonly style="background:var(--surface);color:var(--text3);cursor:not-allowed;font-style:italic">
        </div>
        <div class="env-hint" v-if="envHint">
          通过环境变量设置: <code>{{ envHint }}</code>
        </div>
        <div class="env-hint" v-else>
          此字段仅支持环境变量或手动编辑 config.yaml
        </div>
      </template>

      <!-- Bool toggle -->
      <template v-else-if="field.type === 'bool'">
        <div class="toggle-wrap">
          <label class="toggle">
            <input type="checkbox" :checked="currentVal" @change="$emit('update', field.path, $event.target.checked)">
            <span class="toggle-slider"></span>
          </label>
          <span class="toggle-label">{{ currentVal ? '已启用' : '已关闭' }}</span>
        </div>
      </template>

      <!-- Select (static) -->
      <template v-else-if="field.type === 'select' && !field.source">
        <select :value="currentVal" @change="$emit('update', field.path, $event.target.value)">
          <option v-for="opt in field.options" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
        </select>
      </template>

      <!-- Select (dynamic) -->
      <template v-else-if="field.type === 'select' && field.source">
        <select :value="currentVal" @change="onDynamicSelectChange">
          <option value="">-- 请选择 --</option>
          <option v-for="item in dynamicOptions" :key="optionValue(item)" :value="optionValue(item)">
            {{ optionLabel(item) }}
          </option>
        </select>
        <div v-if="field.source === 'characters' && selectedChar" class="char-preview">
          <span class="char-preview-name">{{ selectedChar.name }}</span>
          <span class="char-preview-path">{{ selectedChar.path }}</span>
        </div>
      </template>

      <!-- Number -->
      <template v-else-if="field.type === 'number'">
        <input type="number" :value="currentVal"
               @input="$emit('update', field.path, $event.target.value === '' ? '' : Number($event.target.value))"
               style="max-width:480px">
      </template>

      <!-- Range -->
      <template v-else-if="field.type === 'range'">
        <div class="range-wrap">
          <input type="range" :value="currentVal ?? field.min ?? 0"
                 :min="field.min ?? 0" :max="field.max ?? 1" :step="field.step ?? 0.01"
                 @input="$emit('update', field.path, Number($event.target.value))">
          <span class="range-val">{{ Number(currentVal ?? field.min ?? 0).toFixed(2) }}</span>
        </div>
      </template>

      <!-- Tags -->
      <template v-else-if="field.type === 'tags'">
        <tags-input :model-value="currentVal || []"
                    @update:model-value="$emit('update', field.path, $event)"></tags-input>
      </template>

      <!-- Object-list -->
      <template v-else-if="field.type === 'object-list'">
        <object-list :value="currentVal || []" :item-fields="field.itemFields"
                     @update="$emit('update', field.path, $event)"></object-list>
      </template>

      <!-- Text (default) -->
      <template v-else>
        <input type="text" :value="currentVal"
               @input="$emit('update', field.path, $event.target.value)"
               style="max-width:480px">
      </template>
    </div>
  `,
  computed: {
    currentVal() {
      return getVal(this.configData, this.field.path);
    },
    visible() {
      if (!this.field.showWhen) return true;
      const val = getVal(this.configData, this.field.showWhen.field);
      return String(val) === String(this.field.showWhen.equals);
    },
    envHint() {
      return this.envHints[this.field.path] || '';
    },
    dynamicOptions() {
      return this.optionsData[this.field.source] || [];
    },
    selectedChar() {
      if (this.field.source !== 'characters') return null;
      return this.dynamicOptions.find(i => i.path === this.currentVal);
    },
  },
  methods: {
    optionValue(item) {
      if (this.field.source === 'characters') return item.path;
      if (this.field.source === 'lora_adapters') return item.path;
      if (this.field.source === 'tts_voices') return item.id;
      if (this.field.source === 'embedding_models') return item.id;
      if (this.field.source === 'knowledge_dirs') return item;
      return item;
    },
    optionLabel(item) {
      if (this.field.source === 'characters') return `${item.name}（${item.file}）`;
      if (this.field.source === 'lora_adapters') return item.name;
      if (this.field.source === 'tts_voices') return item.name;
      if (this.field.source === 'embedding_models') return item.name;
      if (this.field.source === 'knowledge_dirs') return item;
      return item;
    },
    onDynamicSelectChange(e) {
      this.$emit('update', this.field.path, e.target.value);
    },
  },
});

// =============================================================================
// Tags Input Component
// =============================================================================

app.component('tags-input', {
  props: ['modelValue'],
  emits: ['update:modelValue'],
  data() {
    return { inputVal: '' };
  },
  template: `
    <div class="tags-container" @click="$refs.input.focus()">
      <span v-for="(item, i) in modelValue" :key="i" class="tag">
        <span>{{ item }}</span>
        <span class="tag-remove" @click.stop="remove(i)">&times;</span>
      </span>
      <input ref="input" class="tags-input" v-model="inputVal"
             placeholder="输入后按 Enter 添加..."
             @keydown.enter.prevent="add"
             @keydown.backspace="onBackspace">
    </div>
  `,
  methods: {
    add() {
      const v = this.inputVal.trim();
      if (v) {
        this.$emit('update:modelValue', [...this.modelValue, v]);
        this.inputVal = '';
      }
    },
    remove(i) {
      const copy = [...this.modelValue];
      copy.splice(i, 1);
      this.$emit('update:modelValue', copy);
    },
    onBackspace() {
      if (!this.inputVal && this.modelValue.length) {
        this.$emit('update:modelValue', this.modelValue.slice(0, -1));
      }
    },
  },
});

// =============================================================================
// Object List Component (collapsible cards)
// =============================================================================

app.component('object-list', {
  props: ['value', 'itemFields'],
  emits: ['update'],
  data() {
    return { openItems: {} };
  },
  template: `
    <div class="object-list">
      <div v-for="(item, idx) in value" :key="idx" class="object-list-item">
        <div class="object-item-header" @click="toggle(idx)">
          <span class="object-item-summary">{{ summary(item, idx) }}</span>
          <span class="object-item-actions">
            <button class="object-item-btn" type="button">{{ openItems[idx] ? '▲' : '▼' }}</button>
            <button class="object-item-btn danger" type="button" @click.stop="removeItem(idx)">✕</button>
          </span>
        </div>
        <div class="object-item-body" :class="{ open: openItems[idx] }">
          <div v-for="f in itemFields" :key="f.key" class="field-group">
            <label class="field-label">{{ f.label }}</label>
            <template v-if="f.type === 'tags'">
              <tags-input :model-value="item[f.key] || []"
                          @update:model-value="val => updateItemKey(idx, f.key, val)"></tags-input>
            </template>
            <template v-else>
              <input type="text" :value="item[f.key] || ''"
                     @input="e => updateItemKey(idx, f.key, e.target.value)">
            </template>
          </div>
        </div>
      </div>
      <button class="object-list-add" type="button" @click="addItem">+ 添加</button>
    </div>
  `,
  methods: {
    summary(item, idx) {
      const firstText = this.itemFields.find(f => f.type === 'text' || !f.type);
      const val = firstText ? (item[firstText.key] || '') : '';
      return val || `项目 #${idx + 1}`;
    },
    toggle(idx) {
      this.openItems = { ...this.openItems, [idx]: !this.openItems[idx] };
    },
    addItem() {
      const obj = {};
      this.itemFields.forEach(f => { obj[f.key] = f.type === 'tags' ? [] : ''; });
      this.$emit('update', [...this.value, obj]);
    },
    removeItem(idx) {
      const copy = [...this.value];
      copy.splice(idx, 1);
      this.$emit('update', copy);
    },
    updateItemKey(idx, key, val) {
      const copy = this.value.map((item, i) => {
        if (i !== idx) return item;
        return { ...item, [key]: val };
      });
      this.$emit('update', copy);
    },
  },
});

// =============================================================================
// Mount Vue app
// =============================================================================

app.mount('#app');

// =============================================================================
// 侧边栏导航（原生 JS，与 Vue 共享 currentSectionRef）
// =============================================================================

document.getElementById('navList').addEventListener('click', (e) => {
  const item = e.target.closest('.nav-item');
  if (item?.dataset.section) {
    // 更新 Vue 响应式数据
    window.currentSectionRef.value = item.dataset.section;
    // 更新侧边栏高亮
    document.querySelectorAll('.nav-item').forEach(el => {
      el.classList.toggle('active', el.dataset.section === item.dataset.section);
    });
  }
});
