import { CloseOutlined } from '@ant-design/icons';
import { Collapse } from 'antd';
import { TraceEntry } from './NodeConfigForm';

export interface NodeDebugInfo {
  status: 'running' | 'success' | 'error';
  inputs?: any;
  outputs?: any;
  duration_ms?: number;
  error?: string;
  streamingText?: string;
  trace?: Array<{ type: string; payload: Record<string, any> }>;
}

// 右侧节点调试面板（B8）：全图试运行过程中逐节点的输入/输出/耗时/trace
export function NodeDebugPanel({ debugMap, onClose }: {
  debugMap: Record<string, NodeDebugInfo>;
  onClose: () => void;
}) {
  if (Object.keys(debugMap).length === 0) return null;
  return (
      <div style={{
        position: 'absolute', top: 48, right: 16, zIndex: 100,
        width: 320, maxHeight: 'calc(100% - 120px)', overflowY: 'auto',
        background: '#fff', borderRadius: 8, boxShadow: '0 4px 16px rgba(0,0,0,0.12)',
        padding: 12,
      }}>
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          fontSize: 13, fontWeight: 600, marginBottom: 8,
        }}>
          <span>节点调试</span>
          <CloseOutlined
            aria-label="关闭节点调试"
            onClick={onClose}
            style={{ fontSize: 12, color: '#999', cursor: 'pointer' }}
          />
        </div>
        <Collapse
          size="small"
          items={Object.entries(debugMap).map(([nodeId, info]) => {
            const statusColor = info.status === 'error' ? '#ff4d4f' : info.status === 'success' ? '#52c41a' : '#1677ff';
            return {
              key: nodeId,
              label: (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                  <span style={{ width: 8, height: 8, borderRadius: '50%', background: statusColor }} />
                  <span style={{ fontFamily: 'monospace' }}>{nodeId}</span>
                  {info.duration_ms != null && (
                    <span style={{ color: '#999', marginLeft: 'auto' }}>{info.duration_ms}ms</span>
                  )}
                </div>
              ),
              children: (
                <div style={{ fontSize: 11, fontFamily: 'monospace' }}>
                  {info.inputs != null && (
                    <div style={{ marginBottom: 6 }}>
                      <div style={{ color: '#999' }}>输入：</div>
                      <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                        {JSON.stringify(info.inputs, null, 2)}
                      </pre>
                    </div>
                  )}
                  {info.streamingText != null && info.streamingText !== '' && (
                    <div style={{ marginBottom: 6 }}>
                      <div style={{ color: '#1677ff' }}>流式输出：</div>
                      <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                        {info.streamingText}
                      </pre>
                    </div>
                  )}
                  {info.outputs != null && (
                    <div style={{ marginBottom: 6 }}>
                      <div style={{ color: '#999' }}>输出：</div>
                      <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                        {JSON.stringify(info.outputs, null, 2)}
                      </pre>
                    </div>
                  )}
                  {info.error && (
                    <div style={{ color: '#ff4d4f' }}>
                      <div>错误：</div>
                      <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{info.error}</pre>
                    </div>
                  )}
                  {info.trace && info.trace.length > 0 && (
                    <div style={{ marginTop: 6, borderTop: '1px dashed #eee', paddingTop: 6 }}>
                      <div style={{ color: '#999', marginBottom: 4 }}>运行 trace（{info.trace.length} 条）：</div>
                      {info.trace.map((t, idx) => (
                        <TraceEntry key={idx} entry={t} />
                      ))}
                    </div>
                  )}
                </div>
              ),
            };
          })}
        />
      </div>
  );
}
