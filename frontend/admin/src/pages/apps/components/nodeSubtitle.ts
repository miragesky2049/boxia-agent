// 根据节点类型与配置生成节点卡片副标题（与 Coze 行为对齐）
// 返回空字符串时不渲染副标题行

export function buildNodeSubtitle(
  typeKey: string,
  config: Record<string, any> | undefined,
): string {
  if (!config) return '';

  switch (typeKey) {
    case 'llm': {
      const model = config.modleName || config.model || config.model_name || '';
      return model ? `模型: ${model}` : '';
    }
    case 'http': {
      const method = (config.method || 'GET').toString().toUpperCase();
      const url = (config.url || '').toString();
      if (!url) return method;
      const short = url.length > 32 ? `${url.slice(0, 32)}…` : url;
      return `${method} ${short}`;
    }
    case 'if_else': {
      const cases = Array.isArray(config.cases) ? config.cases.length : 0;
      return cases > 0 ? `${cases} 个条件` : '条件分支';
    }
    case 'code':
      return '执行代码';
    case 'dataset':
    case 'dataset_write': {
      const id = config.datasetId || config.dataset_id || '';
      return id ? `知识库: ${id}` : '检索知识库';
    }
    case 'loop': {
      const count = config.loopCount || config.count || '';
      return count ? `循环 ${count} 次` : '循环';
    }
    case 'batch':
      return '批量处理';
    case 'subworkflow': {
      const name = config.workflowName || config.workflow_name || config.subworkflow_id || '';
      return name ? `子流程: ${name}` : '子流程';
    }
    case 'variable_set':
      return '赋值变量';
    case 'variable_merge':
      return '合并变量';
    case 'text_processor':
      return '文本处理';
    case 'json_tools':
      return 'JSON 处理';
    case 'conversation_create':
      return '创建会话';
    case 'conversation_update':
      return '更新会话';
    case 'conversation_list':
      return '查询会话';
    case 'conversation_history':
      return '会话历史';
    case 'message_create':
      return '发送消息';
    case 'message_update':
      return '更新消息';
    case 'message_list':
      return '查询消息';
    case 'message_delete':
      return '删除消息';
    case 'human_task':
      return '人工审批';
    case 'api_plugin': {
      const name = config.pluginName || config.plugin_name || config.tool_name || '';
      return name ? `插件: ${name}` : '插件';
    }
    case 'agent_loop':
      return 'Agent 循环';
    case 'start':
      return '工作流入口';
    case 'end':
      return '工作流结束';
    default:
      return '';
  }
}
