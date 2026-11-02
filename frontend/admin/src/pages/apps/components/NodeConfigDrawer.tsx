import { Button, Drawer, Tag, Typography } from 'antd';
import type { NodeMeta } from '../../../api/nodeMeta';
import type { DatasetItem } from '../../../api/datasets';
import type { NodeDebugRunResult } from '../../../api/apps';
import { canDelete } from '../canvas/metadata/capabilities';
import { CANVAS_TOKENS } from '../canvas/tokens';
import { NodeIcon } from './NodeIcon';
import {
  NodeConfigForm,
  type GraphNodeSummary,
  type NodeConfigValues,
  type OutputFieldItem,
  type UpstreamInputGroup,
} from './NodeConfigForm';

// 节点配置抽屉：字段表单 + 单节点试运行（N9-03）
export function NodeConfigDrawer({
  open,
  nodeId,
  meta,
  values,
  onChange,
  pickerNodes,
  keyToMeta,
  outputs,
  onOutputsChange,
  datasetOptions,
  upstreamInputs,
  onAddNext,
  onClose,
  onRequestDelete,
  debugRunning,
  debugResult,
  onDebug,
}: {
  open: boolean;
  nodeId: string | null;
  meta: NodeMeta | null;
  values: NodeConfigValues;
  onChange: (patch: Partial<NodeConfigValues>) => void;
  pickerNodes: GraphNodeSummary[];
  keyToMeta: Record<string, NodeMeta>;
  outputs: OutputFieldItem[];
  onOutputsChange: (next: OutputFieldItem[]) => void;
  datasetOptions?: DatasetItem[];
  upstreamInputs?: UpstreamInputGroup[];
  onAddNext: (typeKey: string) => void;
  onClose: () => void;
  onRequestDelete: () => void;
  debugRunning: boolean;
  debugResult: NodeDebugRunResult | null;
  onDebug: () => void;
}) {
  return (
    <Drawer
      title={meta ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <NodeIcon
            typeKey={meta.type_key}
            color={meta.color}
            icon={meta.icon}
            size={28}
          />
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 15, fontWeight: 600, lineHeight: '20px' }}>
              {meta.title}
            </div>
            {meta.description && (
              <div style={{
                fontSize: 12, color: '#6b7280', fontWeight: 400, lineHeight: '16px',
                whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
              }}>
                {meta.description}
              </div>
            )}
            {nodeId && (
              <Typography.Text
                type="secondary"
                style={{ fontSize: 12, fontFamily: 'monospace', lineHeight: '16px' }}
                copyable={{ text: nodeId, tooltips: ['复制节点 ID', '已复制'] }}
              >
                <span style={{ color: '#9ca3af' }}>ID </span>{nodeId}
              </Typography.Text>
            )}
          </div>
        </div>
      ) : ''}
      open={open && !!nodeId}
      onClose={onClose}
      width="min(480px, 92vw)"
      extra={
        nodeId && meta && canDelete(meta) ? (
          <Button danger size="small" onClick={onRequestDelete}>
            删除节点
          </Button>
        ) : undefined
      }
    >
      {meta && (
        <NodeConfigForm
          nodeMeta={meta}
          values={values}
          onChange={onChange}
          pickerNodes={pickerNodes}
          currentNodeId={nodeId}
          keyToMeta={keyToMeta}
          outputs={outputs}
          onOutputsChange={onOutputsChange}
          datasetOptions={datasetOptions}
          upstreamInputs={upstreamInputs}
          onAddNext={onAddNext}
        />
      )}
      <div style={{ marginTop: 16, borderTop: `1px solid ${CANVAS_TOKENS.border}`, paddingTop: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
          <Button
            size="small"
            type="primary"
            loading={debugRunning}
            onClick={onDebug}
          >
            试运行此节点
          </Button>
          <span style={{ fontSize: 12, color: '#9ca3af' }}>仅执行当前节点，不影响全图运行</span>
        </div>
        {debugResult && (
          <div style={{ fontSize: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
              <Tag color={debugResult.status === 'success' ? 'green' : 'red'}>
                {debugResult.status === 'success' ? '成功' : '失败'}
              </Tag>
              <span style={{ color: '#9ca3af' }}>{debugResult.duration_ms}ms</span>
            </div>
            {debugResult.error && (
              <pre style={{
                margin: '0 0 6px', color: CANVAS_TOKENS.danger,
                whiteSpace: 'pre-wrap', wordBreak: 'break-all',
              }}>
                {debugResult.error}
              </pre>
            )}
            <div style={{ color: '#9ca3af', marginBottom: 2 }}>输出：</div>
            <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
              {JSON.stringify(debugResult.outputs, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </Drawer>
  );
}
