import type { Locale } from './context';

export type GlossaryMetricId =
  | 'leverage'
  | 'yield'
  | 'active_ratio'
  | 'tokens_per_second'
  | 'bottleneck';

export interface GlossaryEntry {
  term: string;
  short: string;
  definition: string;
  formula: string;
  inputs: string;
  notes: string;
  closeLabel: string;
}

const glossary: Record<GlossaryMetricId, Record<Locale, GlossaryEntry>> = {
  leverage: {
    en: {
      term: 'Leverage',
      short: 'Output produced per unit of user input.',
      definition:
        'Leverage estimates how much model/tool output is generated for each unit of user input in the same scope.',
      formula: '(model output + tool output) / user input',
      inputs: 'Token counts or character counts extracted from parsed session messages and tool results.',
      notes:
        'A high ratio can indicate efficient delegation, but may also include irrelevant output. Interpret with quality context.',
      closeLabel: 'Close',
    },
    'zh-CN': {
      term: '杠杆',
      short: '单位用户输入驱动的输出规模。',
      definition: '杠杆用于估算在同一统计范围内，每单位用户输入能撬动多少模型/工具输出。',
      formula: '（模型输出 + 工具输出）/ 用户输入',
      inputs: '来自解析后会话消息与工具结果的 token 或字符统计。',
      notes: '比值高并不一定代表质量高，仍需结合结果有效性与返工率判断。',
      closeLabel: '关闭',
    },
  },
  yield: {
    en: {
      term: 'Yield Ratio',
      short: 'Legacy naming for leverage-style output efficiency.',
      definition:
        'Yield ratio is the historical name for output/input efficiency and is aligned with leverage metrics in this dashboard.',
      formula: '(model output + tool output) / user input',
      inputs: 'Same source fields as leverage metrics.',
      notes: 'Prefer Leverage wording in UI; Yield is kept for compatibility with older statistics fields.',
      closeLabel: 'Close',
    },
    'zh-CN': {
      term: '产出比',
      short: '杠杆指标的历史命名。',
      definition: '产出比是历史字段命名，与当前界面中的杠杆指标语义一致。',
      formula: '（模型输出 + 工具输出）/ 用户输入',
      inputs: '与杠杆使用同一组统计字段。',
      notes: '界面建议使用“杠杆”术语；“产出比”仅用于兼容旧字段。',
      closeLabel: '关闭',
    },
  },
  active_ratio: {
    en: {
      term: 'Active Ratio',
      short: 'Share of active work time within total observed time.',
      definition:
        'Active ratio measures how much of the observed timeline was spent in model/tool/user active intervals rather than inactive gaps.',
      formula: '(model time + tool time + user time) / total time',
      inputs: 'Time-breakdown buckets computed from message timestamps and inactivity thresholds.',
      notes: 'Sensitive to inactivity threshold configuration and missing timestamps.',
      closeLabel: 'Close',
    },
    'zh-CN': {
      term: '活跃占比',
      short: '总时长中真实工作时段的比例。',
      definition: '活跃占比衡量观测时间内，模型/工具/用户活跃时段相对总时长（含非活跃）的占比。',
      formula: '（模型时间 + 工具时间 + 用户时间）/ 总时间',
      inputs: '基于消息时间戳与非活跃阈值计算的时间分桶。',
      notes: '该指标受非活跃阈值配置与时间戳完整性影响。',
      closeLabel: '关闭',
    },
  },
  tokens_per_second: {
    en: {
      term: 'Tokens per Second',
      short: 'Model throughput normalized by active generation time.',
      definition:
        'Token/s metrics estimate generation throughput, including read/output/cache variants, normalized by model active runtime.',
      formula: 'token count / model active seconds',
      inputs: 'Token usage fields and model-time buckets from session statistics.',
      notes: 'Network delays and batching can skew instantaneous rates; compare median/p90 with mean.',
      closeLabel: 'Close',
    },
    'zh-CN': {
      term: 'Token 每秒',
      short: '按模型活跃时间归一化的吞吐率。',
      definition: 'tok/s 指标用于估算生成吞吐，包含 read/output/cache 等分项，按模型活跃时长归一化。',
      formula: 'token 数量 / 模型活跃秒数',
      inputs: '会话统计中的 token 字段与模型时间分桶。',
      notes: '网络抖动与批处理会影响瞬时速率，建议结合中位数与 P90 解读。',
      closeLabel: '关闭',
    },
  },
  bottleneck: {
    en: {
      term: 'Bottleneck',
      short: 'Dominant limiting factor among model, tool, and user phases.',
      definition:
        'Bottleneck indicates which category contributes the largest active-time share, signaling where optimization likely yields most impact.',
      formula: 'argmax(model %, tool %, user %)',
      inputs: 'Active-time percentage distribution by category per session or aggregated window.',
      notes: 'Bottleneck is descriptive, not causal proof. Validate with raw timeline and error traces.',
      closeLabel: 'Close',
    },
    'zh-CN': {
      term: '瓶颈',
      short: '模型/工具/用户中当前最限制效率的主导环节。',
      definition: '瓶颈表示活跃时间占比最高的类别，可用于判断优先优化方向。',
      formula: 'argmax(模型占比, 工具占比, 用户占比)',
      inputs: '按类别统计的活跃时间占比（单会话或跨会话聚合）。',
      notes: '瓶颈是描述性信号，不代表因果结论；需结合时间线与错误细节复核。',
      closeLabel: '关闭',
    },
  },
};

export function getGlossaryEntry(metricId: GlossaryMetricId, locale: Locale): GlossaryEntry {
  return glossary[metricId][locale];
}
