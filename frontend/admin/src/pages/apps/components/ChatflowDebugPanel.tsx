import { CloseOutlined, PlusOutlined, SendOutlined } from '@ant-design/icons';
import { Button, Input, Tag } from 'antd';
import { useEffect, useRef, useState } from 'react';

export interface ChatflowChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  kind?: 'question' | 'error' | 'info';
}

export interface ChatflowPendingQuestion {
  nodeId: string;
  question: string;
  options: string[];
  threadId: string;
  runId: string;
}

interface ChatflowDebugPanelProps {
  open: boolean;
  running: boolean;
  messages: ChatflowChatMessage[];
  conversationId: string | null;
  pendingQuestion: ChatflowPendingQuestion | null;
  onClose: () => void;
  onNewSession: () => void;
  onSend: (text: string) => void;
  onAnswer: (text: string) => void;
}

function bubbleStyle(role: ChatflowChatMessage['role'], kind?: ChatflowChatMessage['kind']) {
  if (kind === 'error') {
    return { background: '#fff2f0', color: '#a8071a', border: '1px solid #ffccc7' };
  }
  if (role === 'user') return { background: '#1677ff', color: '#fff' };
  if (kind === 'question') return { background: '#f6ffed', color: '#135200', border: '1px solid #b7eb8f' };
  return { background: '#f5f5f5', color: '#1f1f1f' };
}

// 对话流试运行面板：多轮消息、中间输出、问答中断与人审中断统一入口
export function ChatflowDebugPanel({
  open,
  running,
  messages,
  conversationId,
  pendingQuestion,
  onClose,
  onNewSession,
  onSend,
  onAnswer,
}: ChatflowDebugPanelProps) {
  const [draft, setDraft] = useState('');
  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, running, pendingQuestion]);

  if (!open) return null;

  const submit = () => {
    const text = draft.trim();
    if (!text || running) return;
    if (pendingQuestion) onAnswer(text);
    else onSend(text);
    setDraft('');
  };

  return (
    <div style={{
      position: 'absolute', top: 48, right: 16, zIndex: 100,
      width: 400, maxHeight: 'calc(100% - 120px)', height: 'calc(100% - 120px)',
      background: '#fff', borderRadius: 8, boxShadow: '0 4px 16px rgba(0,0,0,0.12)',
      display: 'flex', flexDirection: 'column', overflow: 'hidden',
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '10px 12px', borderBottom: '1px solid #f0f0f0', flexShrink: 0,
      }}>
        <span style={{ fontSize: 13, fontWeight: 600 }}>对话试运行</span>
        {conversationId && (
          <Tag style={{ marginInlineEnd: 0, fontSize: 10 }} color="default">
            会话 {conversationId.slice(0, 8)}
          </Tag>
        )}
        <Button
          size="small"
          icon={<PlusOutlined />}
          style={{ marginLeft: 'auto' }}
          onClick={onNewSession}
          disabled={running}
        >
          新会话
        </Button>
        <CloseOutlined
          aria-label="关闭对话试运行"
          onClick={onClose}
          style={{ fontSize: 12, color: '#999', cursor: 'pointer' }}
        />
      </div>

      <div ref={listRef} style={{ flex: 1, overflowY: 'auto', padding: 12 }}>
        {messages.length === 0 ? (
          <div style={{ color: '#999', fontSize: 12, textAlign: 'center', marginTop: 24 }}>
            发送一条消息开始试运行
          </div>
        ) : (
          messages.map((item) => (
            <div
              key={item.id}
              style={{
                display: 'flex',
                justifyContent: item.role === 'user' ? 'flex-end' : 'flex-start',
                marginBottom: 10,
              }}
            >
              <div style={{
                maxWidth: '85%', padding: '6px 10px', borderRadius: 8, fontSize: 12,
                whiteSpace: 'pre-wrap', wordBreak: 'break-word', ...bubbleStyle(item.role, item.kind),
              }}>
                {item.content}
              </div>
            </div>
          ))
        )}
        {running && (
          <div style={{ color: '#1677ff', fontSize: 12, marginBottom: 10 }}>运行中…</div>
        )}
      </div>

      {pendingQuestion && (
        <div style={{ padding: '8px 12px', borderTop: '1px solid #f0f0f0', flexShrink: 0 }}>
          {pendingQuestion.options.length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
              {pendingQuestion.options.map((option) => (
                <Button
                  key={option}
                  size="small"
                  disabled={running}
                  onClick={() => onAnswer(option)}
                >
                  {option}
                </Button>
              ))}
            </div>
          )}
          <div style={{ fontSize: 11, color: '#8c8c8c' }}>
            等待回答：{pendingQuestion.question || pendingQuestion.nodeId}
          </div>
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, padding: 12, borderTop: '1px solid #f0f0f0', flexShrink: 0 }}>
        <Input.TextArea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={pendingQuestion ? '输入对问题的回答' : '输入消息，Enter 发送'}
          autoSize={{ minRows: 1, maxRows: 4 }}
          onPressEnter={(e) => {
            if (!e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <Button
          type="primary"
          icon={<SendOutlined />}
          loading={running}
          disabled={!draft.trim()}
          onClick={submit}
        />
      </div>
    </div>
  );
}
