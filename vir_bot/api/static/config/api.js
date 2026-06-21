// =============================================================================
// Config API — 并行获取所有配置数据
// =============================================================================

const ConfigAPI = {
  async fetchAll() {
    const [sectionsRes, hintsRes, sensitiveRes, optionsRes] = await Promise.all([
      fetch('/api/config/sections'),
      fetch('/api/config/env-hints'),
      fetch('/api/config/sensitive-fields'),
      fetch('/api/config/options'),
    ]);

    // 检查所有响应状态
    const errors = [];
    if (!sectionsRes.ok) errors.push(`sections(${sectionsRes.status})`);
    if (!hintsRes.ok) errors.push(`env-hints(${hintsRes.status})`);
    if (!sensitiveRes.ok) errors.push(`sensitive-fields(${sensitiveRes.status})`);
    if (!optionsRes.ok) errors.push(`options(${optionsRes.status})`);
    if (errors.length > 0) throw new Error(`API 请求失败: ${errors.join(', ')}`);

    return {
      configData: (await sectionsRes.json()).sections || {},
      envHints: (await hintsRes.json()).hints || {},
      sensitiveFields: (await sensitiveRes.json()).fields || [],
      optionsData: await optionsRes.json(),
    };
  },

  async save(sectionKey, body) {
    const res = await fetch(`/api/config/sections/${sectionKey}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const e = await res.json().catch(() => ({}));
      throw new Error(e.detail || '保存失败');
    }
    return await res.json();
  },
};
