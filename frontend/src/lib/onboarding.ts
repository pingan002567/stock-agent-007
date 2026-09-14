/** 开始使用：何时弹出全屏向导，以及进主界面后的白话开场。 */

export const STARTER_PROMPTS = [
  {
    label: "你现在能做什么？",
    prompt: "你现在能做什么？列出你会用到的工作台能力，没有的不要编。说明你可以给目标价与操作观点，但那不构成投资建议，也不会下单。",
  },
  {
    label: "帮我看看这三笔演示持仓",
    prompt: "帮我看看当前这三笔演示持仓分别是什么、权重如何。说明这是演示数据，不要当成真实仓位，也不要下单。",
  },
  {
    label: "帮我找几只值得先了解的股票",
    prompt: "帮我从当前自选和常见热门股里找出 3 只值得先了解的股票，说明为什么。没有拉到的数字不要编造。",
  },
] as const;

export const EMPTY_CHAT_COPY = {
  title: "从一句问题开始",
  desc: "可给目标价与操作指令，不下单。结论仅供研究参考，不构成投资建议。",
} as const;

export const SETUP_WIZARD_COPY = {
  step2Title: "接上一个对话模型",
  step2Lead: "助手要用模型才能回答。密钥只保存在这台电脑，不会上传到我们的服务器。",
  step3Title: "准备你的工作台",
  step3Lead: "接下来会自动做好这三件事，不用再填表。",
  step3Items: [
    "开一个新对话，方便你马上提问。",
    "放入三笔演示持仓（茅台、腾讯、Apple），用来熟悉页面。这不是你的真实持仓，以后可在持仓页清空或改成自己的。",
    "股票行情使用免费公开数据。以后若要用付费数据，再到设置里打开。",
  ],
  next: "下一步",
  enter: "进入工作台",
  back: "返回上一步",
} as const;

export const SETUP_BANNED_COPY = [
  "漏斗",
  "圈候选",
  "体检",
  "深研",
  "提供商",
  "stub",
  "runtime",
  "launchd",
  "doctor",
  "API",
  "密钥入库",
  "档案",
  "data_dir",
] as const;

export type SetupStatusLike = {
  completed?: boolean;
  required?: boolean;
  model_connected?: boolean;
  default_model?: string | null;
};

export function shouldShowSetupWizard(status: SetupStatusLike | null | undefined): boolean {
  if (!status) return false;
  return Boolean(status.required) && !status.completed;
}

export function isSetupModelReady(status: SetupStatusLike | null | undefined): boolean {
  return Boolean(status?.model_connected && status?.default_model);
}

type HealthLike = {
  agent_runtime?: { active_client?: string };
} | null | undefined;

export function isModelReady(health: HealthLike): boolean {
  const client = health?.agent_runtime?.active_client;
  return Boolean(client && client !== "stub");
}

export function copyAvoidsJargon(text: string): boolean {
  return SETUP_BANNED_COPY.every((word) => !text.includes(word));
}

export function collectSetupCopy(): string {
  return [
    EMPTY_CHAT_COPY.title,
    EMPTY_CHAT_COPY.desc,
    SETUP_WIZARD_COPY.step2Title,
    SETUP_WIZARD_COPY.step2Lead,
    SETUP_WIZARD_COPY.step3Title,
    SETUP_WIZARD_COPY.step3Lead,
    ...SETUP_WIZARD_COPY.step3Items,
    SETUP_WIZARD_COPY.next,
    SETUP_WIZARD_COPY.enter,
    SETUP_WIZARD_COPY.back,
    ...STARTER_PROMPTS.flatMap((item) => [item.label, item.prompt]),
  ].join("\n");
}
