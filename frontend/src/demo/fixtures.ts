import { Article, OptimizerTask, PlatformCredential, PromptRule, Series } from '../types';

export const demoMode = import.meta.env.VITE_DEMO === 'true';

export const demoArticles: Article[] = [
  {
    id: 'demo-article-mcp',
    title: 'Agent 不该再复制粘贴：把自媒体收成一套 MCP',
    seriesId: 'demo-series-agent',
    seriesName: 'Agent 写作控制面',
    status: '待全网发布',
    type: '行业深度',
    createdAt: '2026-09-28T09:00:00Z',
    updatedAt: '2026-10-02T11:20:00Z',
    chosenTitle: 'Agent 不该再复制粘贴：把自媒体收成一套 MCP',
    abstract: '文章、版本和发布矩阵放进同一套 Postgres，Cursor 通过 MCP 读写这一份事实。',
    hookScene: '八个后台各贴一次，链接对不上，才是自媒体自动化真正卡住的地方。',
    writingStyle: '克制的工程师写作',
    targetWords: 4200,
    actualWords: 3860,
    outline: [
      { id: 'o1', title: '事实源', subtopics: ['文章', '版本', '发布记录'] },
      { id: 'o2', title: 'MCP', subtopics: ['检索', '改正文', '回写矩阵'] },
    ],
    publications: [
      { platformId: 'juejin', platformName: '掘金', status: 'Published', url: 'https://juejin.cn/user/3294573386554446/posts' },
      { platformId: 'wechat', platformName: '公众号', status: 'Draft' },
      { platformId: 'zhihu', platformName: '知乎', status: 'Pending_Manual' },
    ],
    qualityIssues: [
      {
        id: 'q1',
        category: 'Style',
        severity: 'Warning',
        description: '开头还可以再短一句。',
        attributedModule: 'Style Checker',
        fixed: false,
      },
    ],
  },
  {
    id: 'demo-article-cover',
    title: '封面不要再做成知识卡片墙',
    seriesId: 'demo-series-agent',
    seriesName: 'Agent 写作控制面',
    status: '写作中',
    type: '动手实战',
    createdAt: '2026-10-01T02:00:00Z',
    updatedAt: '2026-10-03T01:10:00Z',
    chosenTitle: '封面不要再做成知识卡片墙',
    abstract: '一张封面只服务这一篇文章：大标题、一个物体、右下角署名。',
    targetWords: 2800,
    actualWords: 1460,
    publications: [
      { platformId: 'xhs', platformName: '小红书', status: 'Draft' },
    ],
  },
  {
    id: 'demo-article-matrix',
    title: '发布矩阵：先记状态，再谈一键分发',
    status: '已发布',
    type: '技术八股',
    createdAt: '2026-09-12T08:00:00Z',
    updatedAt: '2026-09-18T08:00:00Z',
    chosenTitle: '发布矩阵：先记状态，再谈一键分发',
    abstract: '每个平台一条记录：草稿、已发、链接、失败原因。',
    targetWords: 3200,
    actualWords: 3340,
    publications: [
      { platformId: 'csdn', platformName: 'CSDN', status: 'Published', url: 'https://cpt-magician.blog.csdn.net/' },
      { platformId: 'juejin', platformName: '掘金', status: 'Published', url: 'https://juejin.cn/user/3294573386554446/posts' },
    ],
  },
];

export const demoSeries: Series[] = [
  {
    id: 'demo-series-agent',
    name: 'Agent 写作控制面',
    description: '从选题到多平台发布记录的一条链路。',
    coverUrl: '',
    visualStyle: '黛墨描金',
    defaultTitleStyle: '判断先行',
    defaultWritingStyle: '克制的工程师写作',
    defaultCoverPrompt: '一张物体，两行标题，右下角署名。',
    volumes: [
      {
        id: 'vol-1',
        name: '控制面',
        description: '文章库与 MCP',
        topics: [
          { id: 't1', name: '事实源', articles: [{ id: 'demo-article-mcp', title: 'Agent 不该再复制粘贴', status: '待全网发布' }] },
          { id: 't2', name: '封面', articles: [{ id: 'demo-article-cover', title: '封面不要再做成知识卡片墙', status: '写作中' }] },
        ],
      },
    ],
  },
];

export const demoPrompts: PromptRule[] = [
  {
    id: 'prompt-style',
    name: '克制的工程师写作',
    category: 'BodyGeneration',
    content: '每段替读者省时间。该给判断时给判断，幽默只点一下。',
    status: 'Active',
    version: '1.0.0',
    lastUpdated: '2026-10-01',
    author: '计算机魔术师',
  },
];

export const demoCredentials: PlatformCredential[] = [
  {
    id: 'cred-juejin',
    name: '掘金',
    logo: '⛏️',
    type: 'Core',
    username: '演示会话',
    status: 'Healthy',
    lastChecked: '2026-10-03T08:00:00Z',
  },
];

export const demoTasks: OptimizerTask[] = [
  {
    id: 'task-1',
    title: '标题里少一个能核验的事实',
    sourceType: 'Prompt',
    description: '演示任务。正式环境里它会记在审计表上。',
    relatedArticleId: 'demo-article-mcp',
    relatedArticleTitle: 'Agent 不该再复制粘贴：把自媒体收成一套 MCP',
    createdTime: '2026-10-02T03:00:00Z',
    priority: 'Medium',
    status: 'Pending',
  },
];
