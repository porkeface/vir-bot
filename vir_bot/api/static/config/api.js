// =============================================================================
// Config API — 与后端 /api/config/* 交互
// =============================================================================

const ConfigAPI = {
  async fetchAll() {
    const [sectionsRes, hintsRes, sensitiveRes, optionsRes] = await Promise.all([
      fetch('/api/config/sections'),
      fetch('/api/config/env-hints'),
      fetch('/api/config/sensitive-fields'),
      fetch('/api/config/options'),
    ]);
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
      const e = await res.json();
      throw new Error(e.detail || '保存失败');
    }
    return await res.json();
  },
};
