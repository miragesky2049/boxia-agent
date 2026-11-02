// 根据节点类型与配置生成节点卡片副标题（与 Coze 行为对齐）
// type_key 必须与后端 node_meta.py 一致；返回空字符串时不渲染副标题行

function truncate(text: string, max = 32): string {
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

export function buildNodeSubtitle(
  typeKey: string,
  config: Record<string, any> | undefined,
): string {
  const cfg = config || {};

  switch (typeKey) {
    case 'start': {
      const inputs = Array.isArray(cfg.inputs) ? cfg.inputs.length : 0;
      return inputs > 0 ? `${inputs} 个启动参数` : '工作流入口';
    }
    case 'end':
      return '工作流出口';
    case 'comment':
      return '';

    // ---- AI / 逻辑 ----
    case 'llm': {
      const model = cfg.modleName || cfg.model || cfg.model_name || '';
      return model ? `模型: ${truncate(String(model))}` : '调用大模型';
    }
    case 'agent_loop':
      return 'Agent 自主循环';
    case 'http': {
      const method = String(cfg.method || 'GET').toUpperCase();
      const url = String(cfg.url || '');
      return url ? `${method} ${truncate(url)}` : '调用外部接口';
    }
    case 'api_plugin': {
      const name = cfg.pluginName || cfg.plugin_name || cfg.tool_name || '';
      return name ? `插件: ${truncate(String(name))}` : '调用插件';
    }
    case 'code':
      return cfg.code ? 'Python 代码' : '编写 Python 代码';
    case 'if_else': {
      const cases = Array.isArray(cfg.cases) ? cfg.cases.length : 0;
      return cases > 0 ? `${cases} 个条件` : '条件分支';
    }
    case 'intent': {
      const intents = Array.isArray(cfg.intents) ? cfg.intents.length : 0;
      return intents > 0 ? `${intents} 个意图` : '意图分类路由';
    }
    case 'loop': {
      const count = cfg.loopCount || cfg.count || '';
      return count ? `循环 ${count} 次` : '循环执行';
    }
    case 'batch': {
      const pc = cfg.parallelCount || '';
      return pc ? `并发 ${pc}` : '批量处理';
    }
    case 'break':
      return '跳出循环';
    case 'continue':
      return '跳过本次迭代';
    case 'subworkflow': {
      const id = cfg.workflowId || cfg.workflow_id || cfg.workflowName || '';
      return id ? `子流程: ${truncate(String(id))}` : '调用子流程';
    }
    case 'human_approval': {
      const role = cfg.assignee_role || '';
      return role ? `审批人: ${truncate(String(role))}` : '等待人工审批';
    }

    // ---- 数据 ----
    case 'dataset':
    case 'dataset_write':
    case 'dataset_delete': {
      const id = cfg.datasetId || cfg.dataset_id || '';
      if (id) return `知识库: ${truncate(String(id))}`;
      if (typeKey === 'dataset_write') return '写入知识库';
      if (typeKey === 'dataset_delete') return '删除知识库文档';
      return '检索知识库';
    }
    case 'text_processor': {
      const op = cfg.operation || '';
      const opLabel: Record<string, string> = { concat: '拼接', slice: '截取', replace: '替换' };
      return op ? `文本${opLabel[op] || op}` : '文本处理';
    }
    case 'json_stringify':
      return '对象转 JSON 字符串';
    case 'json_parser':
      return 'JSON 字符串转对象';

    // ---- 变量 ----
    case 'set_variable': {
      const name = cfg.variableName || cfg.variable_name || '';
      return name ? `设置 ${truncate(String(name))}` : '给变量赋值';
    }
    case 'variable_merge':
      return '合并分支变量';

    // ---- 会话 / 消息 ----
    case 'create_conversation':
      return cfg.title ? `会话: ${truncate(String(cfg.title))}` : '创建会话';
    case 'update_conversation':
      return cfg.title ? `新标题: ${truncate(String(cfg.title))}` : '更新会话';
    case 'delete_conversation':
      return '删除会话';
    case 'query_conversation_list':
      return '查询会话列表';
    case 'query_conversation_history':
      return cfg.limit ? `最近 ${cfg.limit} 条` : '查询会话历史';
    case 'create_message': {
      if (cfg.content) return truncate(String(cfg.content));
      const roleLabels: Record<string, string> = {
        user: '用户', assistant: '助手', system: '系统', tool: '工具',
      };
      const role = String(cfg.role || 'user');
      return `角色: ${roleLabels[role] || role}`;
    }
    case 'update_message':
      return '更新消息内容';
    case 'delete_message':
      return '删除消息';
    case 'clear_context':
      return '清空会话上下文';

    // ---- 输入 / 输出 ----
    case 'input': {
      const prompt = cfg.prompt || cfg.question || '';
      return prompt ? truncate(String(prompt)) : '等待用户输入';
    }
    case 'question': {
      const prompt = cfg.question || '';
      return prompt ? truncate(String(prompt)) : '等待用户回答';
    }
    case 'output': {
      const content = cfg.content || '';
      return content ? truncate(String(content)) : '输出消息';
    }

    default:
      return '';
  }
}
