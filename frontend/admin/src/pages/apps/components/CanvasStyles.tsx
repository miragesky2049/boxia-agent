import { CANVAS_TOKENS } from '../canvas/tokens'

// 画布全局样式：覆盖 FlowGram 内部类名（端口、连线、运行态高亮等）
export function CanvasStyles() {
  return (
    <style>{`
            .gedit-playground-container {
              position: relative !important;
              width: 100% !important;
              height: 100% !important;
            }
            @keyframes boxia-pulse {
              0%, 100% { box-shadow: 0 0 0 3px rgba(139,92,246,0.4); }
              50% { box-shadow: 0 0 0 6px rgba(139,92,246,0.15); }
            }
            .boxia-node-running {
              animation: boxia-pulse 1.2s ease-in-out infinite;
            }
            .boxia-node-invalid {
              box-shadow: 0 0 0 3px rgba(239,68,68,0.5) !important;
              border-radius: 8px;
            }
            /* ========== 连线样式（V6 对齐 Coze：主色 #5044fc，选中亮青） ==========
               FlowGram 每条连线渲染两个 path：曲线 + 箭头（V 形折线），二者共用同一套样式。
               选中态由 FlowGram 用 path 的 stroke-width 属性区分（2 → 3），
               因此这里不能再给 stroke-width 加 !important，否则选中态被抹平。 */
            .gedit-flow-activity-edge path {
              stroke: ${CANVAS_TOKENS.line} !important;
              fill: none !important;
              transition: stroke 0.15s, stroke-width 0.15s, filter 0.15s;
            }
            .gedit-flow-activity-edge:hover path {
              stroke: ${CANVAS_TOKENS.lineHover} !important;
            }
            .gedit-flow-activity-edge path[stroke-width='3'],
            .gedit-flow-activity-edge:hover path[stroke-width='3'] {
              stroke: ${CANVAS_TOKENS.lineActive} !important;
              filter: drop-shadow(0 0 4px ${CANVAS_TOKENS.lineActiveGlow});
            }
            /* ========== 端口圆点（对齐 Coze 实机） ==========
               FlowGram 端口 DOM：
               <div data-port-entity-id class="WorkflowPointStyle-xxx">  ← 外层 20x20 命中区
                 <div class="bg-circle workflow-bg-circle"/>             ← 白色底圈
                 <div class="bg workflow-port-bg workflow-point-bg">    ← 紫色圆点
                 <div class="focus-circle"/>
               问题：.bg 默认是 position: relative 的流式元素，旧样式把它缩到 12x12 后
                     仍贴在命中区左上角，圆心与白圈圆心差 4px（用户反馈的"端点未居中"）。
               修复：改成绝对定位 + 50%/负 margin 居中，缩放不会破坏圆心位置。 */
            [data-port-entity-id] {
              width: 20px !important;
              height: 20px !important;
              margin-top: -10px !important;
              margin-left: -10px !important;
              background: transparent !important;
              border: none !important;
            }
            [data-port-entity-id] > .bg-circle,
            [data-port-entity-id] > .workflow-bg-circle {
              width: 20px !important;
              height: 20px !important;
              left: 0 !important;
              top: 0 !important;
              background: #fff !important;
              transform: scale(1) !important;
            }
            [data-port-entity-id] > .bg,
            [data-port-entity-id] > .workflow-port-bg,
            [data-port-entity-id] > .workflow-point-bg {
              position: absolute !important;
              left: 50% !important;
              top: 50% !important;
              width: 12px !important;
              height: 12px !important;
              margin: -6px 0 0 -6px !important;
              background: ${CANVAS_TOKENS.port} !important;
              transform: scale(1) !important;
              border: 2px solid ${CANVAS_TOKENS.white} !important;
              box-shadow: 0 0 0 1px ${CANVAS_TOKENS.port} !important;
              cursor: crosshair !important;
            }
            [data-port-entity-id]:hover > .bg,
            [data-port-entity-id]:hover > .workflow-port-bg,
            [data-port-entity-id].hovered > .bg,
            [data-port-entity-id].hovered > .workflow-port-bg {
              background: ${CANVAS_TOKENS.portHover} !important;
              transform: scale(1.15) !important;
            }
            [data-port-entity-id].linked > .bg,
            [data-port-entity-id].linked > .workflow-port-bg {
              background: ${CANVAS_TOKENS.portLinked} !important;
            }
            /* 输出端口 hover：对齐 Coze 的紫色「+」拖拽提示（输入端口保持圆点） */
            [data-port-entity-id][data-port-entity-type='output']:hover > .bg,
            [data-port-entity-id][data-port-entity-type='output'].hovered > .bg {
              width: 18px !important;
              height: 18px !important;
              margin: -9px 0 0 -9px !important;
              background: ${CANVAS_TOKENS.port} !important;
              transform: scale(1) !important;
              box-shadow: 0 0 0 1px ${CANVAS_TOKENS.port}, 0 0 0 5px ${CANVAS_TOKENS.portRing} !important;
            }
            [data-port-entity-id][data-port-entity-type='output']:hover > .bg::after,
            [data-port-entity-id][data-port-entity-type='output'].hovered > .bg::after {
              content: '+';
              position: absolute;
              inset: 0;
              display: flex;
              align-items: center;
              justify-content: center;
              color: #fff;
              font-size: 14px;
              font-weight: 400;
              line-height: 1;
            }
            [data-port-entity-id] > .bg > .cross-hair,
            [data-port-entity-id] .focus-circle {
              display: none !important;
            }
            /* 拖线时命中的可落点输入端口（JS 打标，拖拽中 :hover 不可靠） */
            [data-port-entity-id].boxia-port-drop-target > .bg,
            [data-port-entity-id].boxia-port-drop-target > .workflow-port-bg {
              background: ${CANVAS_TOKENS.portDrop} !important;
              transform: scale(1.35) !important;
            }
            [data-port-entity-id].boxia-port-drop-target {
              border-radius: 50% !important;
              box-shadow: 0 0 0 5px ${CANVAS_TOKENS.portDropRing} !important;
            }
            /* RefChipInput 聚焦态 */
            .boxia-ref-chip-input:focus-within {
              border-color: ${CANVAS_TOKENS.accent} !important;
              box-shadow: 0 0 0 2px ${CANVAS_TOKENS.portRingSoft};
            }
    `}</style>
  )
}
