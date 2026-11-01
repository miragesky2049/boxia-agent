import { useCallback, useEffect, useState } from 'react';
import { Button, Drawer, Empty, Popconfirm, Select, Spin, Tag, message } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import {
  deleteAppConversation,
  deleteAppConversationMessage,
  listAppConversationMessages,
  listAppConversations,
  type AppConversation,
  type AppConversationMessage,
} from '../../../api/apps';
import { listTenants } from '../../../api/tenant';
import type { Tenant } from '../../../api/types';
import { CANVAS_TOKENS } from '../canvas/tokens';

const ROLE_VIEW: Record<string, { text: string; color: string }> = {
  user: { text: '用户', color: 'blue' },
  assistant: { text: '助手', color: 'green' },
  tool: { text: '工具', color: 'purple' },
  system: { text: '系统', color: 'default' },
};

function formatTime(value: string | null): string {
  return value ? dayjs(value).format('MM-DD HH:mm') : '-';
}

interface ConversationDrawerProps {
  open: boolean;
  applicationId: string;
  onClose: () => void;
}

// 应用会话管理（N9-05）：平台管理员按租户排查多轮会话与消息
export function ConversationDrawer({ open, applicationId, onClose }: ConversationDrawerProps) {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [tenantId, setTenantId] = useState<string | undefined>(undefined);
  const [conversations, setConversations] = useState<AppConversation[]>([]);
  const [listLoading, setListLoading] = useState(false);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<AppConversationMessage[]>([]);
  const [messagesLoading, setMessagesLoading] = useState(false);

  // 首次打开拉租户列表；默认切到第一个业务租户，避免只看到平台租户的空列表
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void listTenants({ page_size: 100 })
      .then((result) => {
        if (cancelled) return;
        setTenants(result.items);
        setTenantId((prev) => prev ?? result.items.find((t) => t.code !== 'platform')?.id);
      })
      .catch((err) => {
        if (!cancelled) message.error(err instanceof Error ? err.message : '加载租户列表失败');
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  const loadConversations = useCallback(async () => {
    if (!applicationId) return;
    setListLoading(true);
    try {
      const rows = await listAppConversations(applicationId, { tenantId, limit: 50 });
      setConversations(rows);
      setActiveId((prev) => (prev && rows.some((row) => row.conversation_id === prev) ? prev : null));
    } catch (err) {
      message.error(err instanceof Error ? err.message : '加载会话列表失败');
    } finally {
      setListLoading(false);
    }
  }, [applicationId, tenantId]);

  useEffect(() => {
    if (open) void loadConversations();
  }, [open, loadConversations]);

  const loadMessages = useCallback(async (conversationId: string) => {
    setActiveId(conversationId);
    setMessages([]);
    setMessagesLoading(true);
    try {
      setMessages(await listAppConversationMessages(conversationId, { tenantId }));
    } catch (err) {
      message.error(err instanceof Error ? err.message : '加载会话消息失败');
    } finally {
      setMessagesLoading(false);
    }
  }, [tenantId]);

  const removeConversation = useCallback(async (conversationId: string) => {
    try {
      await deleteAppConversation(conversationId, tenantId);
      message.success('会话已删除');
      if (activeId === conversationId) {
        setActiveId(null);
        setMessages([]);
      }
      await loadConversations();
    } catch (err) {
      message.error(err instanceof Error ? err.message : '删除会话失败');
    }
  }, [tenantId, activeId, loadConversations]);

  const removeMessage = useCallback(async (messageId: string) => {
    if (!activeId) return;
    try {
      await deleteAppConversationMessage(activeId, messageId, tenantId);
      setMessages((prev) => prev.filter((item) => item.message_id !== messageId));
      message.success('消息已删除');
    } catch (err) {
      message.error(err instanceof Error ? err.message : '删除消息失败');
    }
  }, [activeId, tenantId]);

  const activeConversation = conversations.find((c) => c.conversation_id === activeId) ?? null;

  return (
    <Drawer title="会话管理" open={open} onClose={onClose} width="min(760px, 94vw)">
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <Select
          allowClear
          value={tenantId}
          onChange={(value) => setTenantId(value ?? undefined)}
          placeholder="平台租户（默认）"
          style={{ flex: 1 }}
          options={tenants.map((t) => ({ value: t.id, label: `${t.name}（${t.code}）` }))}
        />
        <Button icon={<ReloadOutlined />} loading={listLoading} onClick={() => void loadConversations()}>
          刷新
        </Button>
      </div>

      <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
        <div style={{ width: 280, flexShrink: 0, maxHeight: 'calc(100vh - 240px)', overflowY: 'auto' }}>
          {listLoading && conversations.length === 0 ? (
            <div style={{ padding: 16, textAlign: 'center' }}><Spin size="small" /></div>
          ) : conversations.length === 0 ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="暂无会话"
              style={{ marginTop: 24 }}
            />
          ) : (
            conversations.map((conversation) => {
              const active = conversation.conversation_id === activeId;
              return (
                <div
                  key={conversation.conversation_id}
                  onClick={() => void loadMessages(conversation.conversation_id)}
                  style={{
                    padding: '8px 10px', borderRadius: 6, cursor: 'pointer', marginBottom: 4,
                    background: active ? CANVAS_TOKENS.accentSoft : 'transparent',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span style={{
                      fontSize: 13, fontWeight: 500, color: active ? CANVAS_TOKENS.accentText : '#374151',
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1,
                    }}>
                      {conversation.title || '（无标题）'}
                    </span>
                    <Popconfirm
                      title="删除该会话？"
                      description="会话下的消息会一并删除"
                      okText="删除"
                      cancelText="取消"
                      okButtonProps={{ danger: true }}
                      onConfirm={() => void removeConversation(conversation.conversation_id)}
                    >
                      <Button
                        size="small"
                        type="text"
                        danger
                        onClick={(e) => e.stopPropagation()}
                      >
                        删除
                      </Button>
                    </Popconfirm>
                  </div>
                  <div style={{ display: 'flex', gap: 6, fontSize: 11, color: '#9ca3af', marginTop: 2 }}>
                    <span>{conversation.display_name || conversation.username || '-'}</span>
                    <span style={{ marginLeft: 'auto' }}>{formatTime(conversation.updated_at)}</span>
                  </div>
                </div>
              );
            })
          )}
        </div>

        <div style={{ flex: 1, minWidth: 0, maxHeight: 'calc(100vh - 240px)', overflowY: 'auto' }}>
          {!activeId ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="选择左侧会话查看消息"
              style={{ marginTop: 24 }}
            />
          ) : messagesLoading ? (
            <div style={{ padding: 16, textAlign: 'center' }}><Spin size="small" /></div>
          ) : messages.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无消息" style={{ marginTop: 24 }} />
          ) : (
            messages.map((item) => {
              const role = ROLE_VIEW[item.role] ?? { text: item.role, color: '#6b7280' };
              return (
                <div key={item.message_id} style={{ marginBottom: 10, fontSize: 12 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
                    <Tag color={role.color} style={{ marginInlineEnd: 0 }}>{role.text}</Tag>
                    <span style={{ color: '#9ca3af' }}>{formatTime(item.created_at)}</span>
                    <Popconfirm
                      title="删除该消息？"
                      okText="删除"
                      cancelText="取消"
                      okButtonProps={{ danger: true }}
                      onConfirm={() => void removeMessage(item.message_id)}
                    >
                      <Button size="small" type="text" danger style={{ marginLeft: 'auto' }}>
                        删除
                      </Button>
                    </Popconfirm>
                  </div>
                  <pre style={{
                    margin: 0, padding: '6px 8px', borderRadius: 6, background: '#f9fafb',
                    whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontFamily: 'inherit',
                  }}>
                    {item.content || '（空消息）'}
                  </pre>
                </div>
              );
            })
          )}
          {activeConversation && (
            <div style={{ marginTop: 8, fontSize: 11, color: '#9ca3af' }}>
              会话 ID：{activeConversation.conversation_id}
            </div>
          )}
        </div>
      </div>
    </Drawer>
  );
}
