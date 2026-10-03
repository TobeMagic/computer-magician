/**
 * AImagician Types Definition
 */

export type ArticleStatus =
  | '待研究'      // To Research
  | '待写作'      // To Write
  | '写作中'      // Writing (Ink-on-page)
  | '正在生成'    // Generating
  | '待预览'      // To Preview
  | '已预览'      // Previewed
  | '待全网发布'  // To Distribute
  | '已发布'      // Distributed
  | '已合并覆盖'  // Merged & Overridden
  | '已归档'      // Archived
  | '暂停';        // Paused

export interface ResearchReport {
  summary: string;
  sources: { 
    title: string; 
    url: string; 
    reliability: 'High' | 'Medium' | 'Low'; 
    extract: string;
    query?: string;
    platformName?: string;
    platformIcon?: string;
    platformId?: string;
  }[];
  coveragePercent: number;
  evidenceGaps: string[];
}

export interface TitleCandidate {
  text: string;
  style: string;
  hookDepth: string;
  clicksEstimate: string;
}

export interface OutlineItem {
  id: string;
  title: string;
  subtopics: string[];
}

export interface PublisherProof {
  platformId: string;
  platformName: string;
  status: 'Published' | 'Draft' | 'Failed' | 'Checking' | 'Pending_Manual';
  url?: string;
  draftId?: string;
  publishTime?: string;
  retryCount?: number;
  errorMessage?: string;
}

export interface QualityIssue {
  id: string;
  category: 'Research' | 'Content' | 'Structure' | 'Style' | 'Format' | 'Assets' | 'Render' | 'Publish';
  severity: 'Block' | 'Critical_Warning' | 'Warning';
  description: string;
  attributedModule: string; // e.g. "Draft Generator", "Markdown Formatter", "Cookie session", "Cover Generator"
  fixed: boolean;
}

export interface VersionHistory {
  version: number;
  timestamp: string;
  author: string;
  changesSummary: string;
  content: string;
}

export interface Article {
  id: string;
  title: string;
  seriesId?: string;
  seriesName?: string;
  volumeId?: string;
  topicId?: string;
  status: ArticleStatus;
  type: string; // e.g. "技术八股", "行业深度", "动手实战", "新闻快讯"
  createdAt: string;
  updatedAt: string;
  
  // Research
  researchReport?: ResearchReport;
  
  // Design & Gate Decisions
  titleCandidates?: TitleCandidate[];
  chosenTitle?: string;
  abstract?: string;
  outline?: OutlineItem[];
  hookScene?: string;
  targetWords?: number;
  actualWords?: number;
  writingStyle?: string;
  
  // Drafts
  originalDraft?: string;
  currentContent?: string;
  platformContent?: string; // Standardized markdown/html for WeChat or Hexo
  versions?: VersionHistory[];
  
  // Assets
  coverBrief?: string;
  coverStyleDirection?: string;
  coverCandidates?: string[]; // image URLs
  chosenCover?: string;
  mediaAssets?: { id: string; name: string; type: 'svg' | 'math' | 'reaction' | 'image'; url: string; caption?: string }[];
  
  // Publishing & Verification
  publications?: PublisherProof[];
  
  // Quality & Audit
  qualityIssues?: QualityIssue[];
  
  // Logs & Run traces
  agentLogs?: { timestamp: string; action: string; agent: string; status: 'Success' | 'Warn' | 'Blocked'; detail: string }[];
  
  // Post-mortem
  postMortem?: {
    productionSpeed: string;
    blockersEncountered: string[];
    audienceEngagementNotes?: string;
    promptEnhancementSuggested?: string;
    resolved: boolean;
  };
}

export interface Volume {
  id: string;
  name: string;
  description: string;
  topics: {
    id: string;
    name: string;
    articles: { id: string; title: string; status: ArticleStatus }[];
  }[];
}

export interface Series {
  id: string;
  name: string;
  description: string;
  coverUrl: string;
  visualStyle: string;
  defaultTitleStyle: string;
  defaultWritingStyle: string;
  defaultCoverPrompt: string;
  volumes: Volume[];
}

export interface PromptRule {
  id: string;
  name: string;
  category:
    | 'TopicSelection'
    | 'ResearchExpansion'
    | 'TitleGeneration'
    | 'Abstract'
    | 'Outline'
    | 'Hook'
    | 'BodyGeneration'
    | 'SectionRewrite'
    | 'QualityReview'
    | 'CoverDirection'
    | 'ImagePrompt'
    | 'FormatAdaptation'
    | 'AgentManual';
  content: string;
  status: 'Draft' | 'Testing' | 'Active' | 'Deprecated';
  version: string;
  lastUpdated: string;
  author: string;
}

export interface PlatformCredential {
  id: string;
  name: string;
  logo: string;
  type: 'Preview' | 'Core' | 'Extension';
  username: string;
  status: 'Healthy' | 'Expired' | 'Pending_Captcha' | 'Rate_Limited';
  lastChecked: string;
  failureReason?: string;
  sessionFile?: string;
  requiresAction?: string;
}

export interface ProjectStats {
  articleCount: number;
  seriesCount: number;
  failedPublishes: number;
  activeBlockers: number;
  activeWarnings: number;
  promptEfficiency: string;
  overallProgress: number; // e.g., series percent Completion
}

export interface OptimizerTask {
  id: string;
  title: string;
  sourceType: 'Prompt' | 'Formatter' | 'Publisher' | 'Asset' | 'AgentRunbook' | 'SeriesPlan';
  description: string;
  relatedArticleId?: string;
  relatedArticleTitle?: string;
  attributedIssueId?: string;
  createdTime: string;
  updatedTime?: string;
  priority: 'High' | 'Medium' | 'Low';
  status: 'Pending' | 'Applied' | 'Ignored';
  metadataJson?: Record<string, unknown>;
}

export function mapOptimizerTaskFromApi(apiTask: any): OptimizerTask {
  return {
    id: apiTask.id,
    title: apiTask.title,
    sourceType: apiTask.source_type || 'AgentRunbook',
    description: apiTask.description || '',
    relatedArticleId: apiTask.related_article_id,
    relatedArticleTitle: apiTask.related_article_title,
    attributedIssueId: apiTask.attributed_issue_id,
    createdTime: apiTask.created_at,
    updatedTime: apiTask.updated_at,
    priority: apiTask.priority || 'Medium',
    status: apiTask.status || 'Pending',
    metadataJson: apiTask.metadata_json || {},
  };
}
