import { Tag } from 'antd';
import type { GraphValidationIssue } from '../../../api/apps';
import { CANVAS_TOKENS } from '../canvas/tokens';
import { RunHistoryPanel } from './RunHistoryPanel';

type PanelTab = 'validation' | 'logs' | 'history';

// V1/V2：右下角面板的 Tab 切换小标签
function TabSwitch({
  active, label, onClick,
}: { active: boolean; label: string; onClick: () => void }) {
  return (
    <span
      onClick={onClick}
      style={{
        fontSize: 13, cursor: 'pointer', padding: '4px 8px',
        color: active ? '#4f46e5' : '#6b7280',
        borderBottom: active ? '2px solid #4f46e5' : '2px solid transparent',
        fontWeight: active ? 600 : 400,
      }}
    >
      {label}
    </span>
  );
}

export function BottomStatusPanel({
  applicationId,
  open,
  tab,
  validationIssues,
  runLogs,
  onTabChange,
  onClose,
}: {
  applicationId: string | undefined;
  open: boolean;
  tab: PanelTab;
  validationIssues: GraphValidationIssue[];
  runLogs: Array<{ time: string; text: string; level?: 'info' | 'error' }>;
  onTabChange: (tab: PanelTab) => void;
  onClose: () => void;
}) {
  if (!open) return null;
  return (
    <div style={{
      position: 'absolute', bottom: 80, right: 16, zIndex: 100,
      width: 400, maxHeight: 360, display: 'flex', flexDirection: 'column',
      background: '#fff', borderRadius: 8, boxShadow: '0 4px 16px rgba(0,0,0,0.12)',
      overflow: 'hidden',
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 12,
        padding: '8px 12px', borderBottom: '1px solid #f0f0f0',
      }}>
        <TabSwitch
          active={tab === 'validation'}
          label={`校验${validationIssues.length > 0 ? ` (${validationIssues.length})` : ''}`}
          onClick={() => onTabChange('validation')}
        />
        <TabSwitch
          active={tab === 'logs'}
          label={`日志${runLogs.length > 0 ? ` (${runLogs.length})` : ''}`}
          onClick={() => onTabChange('logs')}
        />
        <TabSwitch
          active={tab === 'history'}
          label="历史"
          onClick={() => onTabChange('history')}
        />
        <span style={{ marginLeft: 'auto', cursor: 'pointer', color: '#999' }} onClick={() => onClose()}>✕</span>
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: 12 }}>
        {tab === 'validation' && (
          validationIssues.length === 0 ? (
            <div style={{ color: '#9ca3af', fontSize: 12, textAlign: 'center', padding: 16 }}>
              暂无校验问题
            </div>
          ) : (
            validationIssues.map((issue, idx) => (
              <div key={idx} style={{
                fontSize: 12, padding: '6px 0',
                color: issue.severity === 'error' ? CANVAS_TOKENS.danger : CANVAS_TOKENS.warning,
                display: 'flex', gap: 8, alignItems: 'flex-start', cursor: 'pointer',
                borderBottom: '1px dashed #f3f4f6',
              }}
                onClick={() => {
                  if (!issue.node_id) return;
                  const el = document.getElementById(issue.node_id);
                  el?.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'center' });
                }}
              >
                <span>{issue.severity === 'error' ? '●' : '▲'}</span>
                <span style={{ flex: 1 }}>{issue.message}</span>
                {issue.node_id && (
                  <Tag style={{ fontSize: 11, marginRight: 0 }}>{issue.node_id}</Tag>
                )}
              </div>
            ))
          )
        )}
        {tab === 'logs' && (
          runLogs.length === 0 ? (
            <div style={{ color: '#9ca3af', fontSize: 12, textAlign: 'center', padding: 16 }}>
              暂无运行日志
            </div>
          ) : (
            <div style={{
              background: 'rgba(0,0,0,0.85)', color: '#d9d9d9',
              borderRadius: 6, padding: 12, fontFamily: 'monospace', fontSize: 12,
              maxHeight: 280, overflowY: 'auto',
            }}>
              {runLogs.map((log, i) => (
                <div key={i} style={{ color: log.level === 'error' ? CANVAS_TOKENS.dangerDot : '#d9d9d9' }}>
                  <span style={{ color: '#666' }}>[{log.time}]</span> {log.text}
                </div>
              ))}
            </div>
          )
        )}
        {tab === 'history' && applicationId && (
          <RunHistoryPanel applicationId={applicationId} active />
        )}
      </div>
    </div>
  );
}
