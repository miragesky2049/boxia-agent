import { request } from './client'
import type { Skill, SkillFile, SkillFileList, SkillFileMeta, SkillFileWritePayload } from './types'

function fileUrl(skillId: string, path?: string): string {
  const base = `/admin/skills/${skillId}/files`
  return path === undefined ? base : `${base}?path=${encodeURIComponent(path)}`
}

/** 技能包虚拟目录：文件读写、zip 导入导出与克隆到当前租户。 */
export const skillPackageApi = {
  async listFiles(skillId: string, prefix?: string): Promise<SkillFileList> {
    const query = prefix ? `?prefix=${encodeURIComponent(prefix)}` : ''
    return request<SkillFileList>(`/admin/skills/${skillId}/files${query}`)
  },
  async readFile(skillId: string, path: string): Promise<SkillFile> {
    return request<SkillFile>(
      `/admin/skills/${skillId}/files/content?path=${encodeURIComponent(path)}`,
    )
  },
  async writeFile(skillId: string, payload: SkillFileWritePayload): Promise<SkillFile> {
    return request<SkillFile>(fileUrl(skillId), {
      method: 'PUT',
      body: JSON.stringify(payload),
    })
  },
  async deleteFile(skillId: string, path: string): Promise<void> {
    await request<void>(fileUrl(skillId, path), { method: 'DELETE' })
  },
  async importZip(skillId: string, file: Blob): Promise<SkillFileMeta[]> {
    return request<SkillFileMeta[]>(`/admin/skills/${skillId}/import`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/zip', Accept: 'application/json' },
      body: file,
    })
  },
  async exportZip(skillId: string): Promise<Blob> {
    return request<Blob>(`/admin/skills/${skillId}/export`, {
      headers: { Accept: 'application/zip' },
      responseType: 'blob',
    })
  },
  async clone(skillId: string, name: string | undefined, agentId: string): Promise<Skill> {
    return request<Skill>(`/admin/skills/${skillId}/clone`, {
      method: 'POST',
      body: JSON.stringify({ name: name?.trim() || null, agent_id: agentId }),
    })
  },
}
