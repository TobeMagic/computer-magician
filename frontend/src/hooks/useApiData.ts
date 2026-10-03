/**
 * useApiData hook
 * Bridges backend API types to frontend component types.
 */

import React, { useState, useEffect, useCallback } from 'react';
import { Article, Series, PromptRule, PlatformCredential, OptimizerTask, mapOptimizerTaskFromApi } from '../types';
import {
  searchArticles,
  getArticle,
  getArticleVersions,
  listSeries,
  getSeries,
  listPrompts,
  listCredentials,
  listOptimizerTasks,
  isAuthenticated,
} from '../api';
import { demoArticles, demoCredentials, demoMode, demoPrompts, demoSeries, demoTasks } from '../demo/fixtures';

interface ApiDataState {
  articles: Article[];
  setArticles: React.Dispatch<React.SetStateAction<Article[]>>;
  seriesList: Series[];
  promptRules: PromptRule[];
  setPromptRules: React.Dispatch<React.SetStateAction<PromptRule[]>>;
  credentials: PlatformCredential[];
  setCredentials: React.Dispatch<React.SetStateAction<PlatformCredential[]>>;
  optimizerTasks: OptimizerTask[];
  setOptimizerTasks: React.Dispatch<React.SetStateAction<OptimizerTask[]>>;
  dashboardStats: {
    articleCount: number;
    seriesCount: number;
    failedPublishes: number;
    activeBlockers: number;
    activeWarnings: number;
    promptEfficiency: string;
    overallProgress: number;
  };
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

function mapArticleFromApi(apiArticle: any): Article {
  const meta = apiArticle.metadata_json || {};
  return {
    id: apiArticle.id || '',
    title: apiArticle.confirmed_title || apiArticle.seed_title || '',
    seriesId: apiArticle.series_id,
    seriesName: apiArticle.series_name,
    status: mapArticleStatus(apiArticle.status),
    type: meta.article_type || apiArticle.article_style_key || '技术八股',
    createdAt: apiArticle.created_at || '',
    updatedAt: apiArticle.updated_at || '',
    targetWords: apiArticle.target_word_count || 2500,
    actualWords: apiArticle.actual_word_count || 0,
    abstract: meta.abstract || apiArticle.summary || '',
    hookScene: meta.hook_scene || apiArticle.opening_hook || '',
    writingStyle: meta.writing_style || apiArticle.article_style_key || '',
    outline: meta.outline || apiArticle.confirmed_outline || [],
    chosenTitle: meta.chosen_title || apiArticle.confirmed_title || apiArticle.seed_title || '',
    // Map backend counts to frontend quality issues
    qualityIssues: [
      ...Array.from({ length: apiArticle.blocking_count || 0 }, (_, i) => ({
        id: `blocking-${apiArticle.id}-${i}`,
        severity: 'Block' as const,
        title: `Blocking issue ${i + 1}`,
        category: 'Content' as const,
        description: `Blocking issue ${i + 1}`,
        attributedModule: '',
        fixed: false,
      })),
      ...Array.from({ length: apiArticle.warning_count || 0 }, (_, i) => ({
        id: `warning-${apiArticle.id}-${i}`,
        severity: 'Critical_Warning' as const,
        title: `Warning ${i + 1}`,
        category: 'Content' as const,
        description: `Warning ${i + 1}`,
        attributedModule: '',
        fixed: false,
      })),
    ],
  };
}

function mapArticleStatus(status: string): any {
  const statusMap: Record<string, any> = {
    'draft': '待写作',
    'researching': '待研究',
    'writing': '写作中',
    'reviewing': '待预览',
    'previewed': '已预览',
    'ready_to_publish': '待全网发布',
    'published': '已发布',
    'archived': '已归档',
  };
  return statusMap[status] || status;
}

function mapSeriesFromApi(apiSeries: any): Series {
  return {
    id: apiSeries.id || '',
    name: apiSeries.name || '',
    description: apiSeries.description || '',
    coverUrl: apiSeries.cover_url || '',
    visualStyle: apiSeries.visual_style || '',
    defaultTitleStyle: apiSeries.default_title_style || '',
    defaultWritingStyle: apiSeries.default_writing_style || '',
    defaultCoverPrompt: apiSeries.default_cover_prompt || '',
    // Map entries if available (from getSeries which returns SeriesWithEntries)
    volumes: (apiSeries.entries || []).map((entry: any) => ({
      id: entry.id || '',
      title: entry.title || entry.confirmed_title || '',
      status: entry.status || 'draft',
      wordCount: entry.word_count || 0,
    })),
  };
}

function mapPromptRuleFromApi(apiPrompt: any): PromptRule {
  return {
    id: apiPrompt.prompt_key || apiPrompt.id || '',
    name: apiPrompt.label || apiPrompt.name || '',
    category: apiPrompt.domain || 'BodyGeneration',
    content: '',
    status: 'Active',
    version: '1.0.0',
    lastUpdated: apiPrompt.updated_at || '',
    author: 'System',
  };
}

function mapCredentialFromApi(apiCred: any): PlatformCredential {
  const readiness = apiCred.readiness || 'unknown';
  const statusMap: Record<string, PlatformCredential['status']> = {
    'ready': 'Healthy',
    'healthy': 'Healthy',
    'active': 'Healthy',
    'pending_captcha': 'Pending_Captcha',
    'pending_sms': 'Pending_Captcha',
    'expired': 'Expired',
    'error': 'Expired',
    'rate_limited': 'Rate_Limited',
    // Hexo: static site, no login required
    'static_site_public_url_check': 'Healthy',
    // Session ready states
    'session_ready': 'Healthy',
    'credential_previously_validated': 'Healthy',
  };
  const blockers = apiCred.blockers_json?.items || [];
  const failureReason = blockers.length > 0 ? blockers[0].message : undefined;
  return {
    id: apiCred.id || apiCred.platform || '',
    name: apiCred.platform || '',
    logo: getPlatformLogo(apiCred.platform),
    type: 'Core',
    username: '',
    status: statusMap[readiness] || statusMap[apiCred.status] || 'Pending_Captcha',
    lastChecked: apiCred.last_checked_at || apiCred.updated_at || '',
    failureReason,
  };
}

function getPlatformLogo(platform: string): string {
  const logos: Record<string, string> = {
    juejin: '⛏️', wechat: '💬', csdn: '💻', zhihu: '📚',
    infoq: '📰', hexo: '🌐', cnblogs: '📝', '51cto': '🔧',
    bilibili: '📺', github: '🐙', toutiao: '📰', sohu: '📰',
  };
  return logos[platform?.toLowerCase()] || '🔑';
}

export function useApiData(isLoggedIn: boolean = false): ApiDataState {
  const [articles, setArticles] = useState<Article[]>(demoMode ? demoArticles : []);
  const [seriesList, setSeriesList] = useState<Series[]>(demoMode ? demoSeries : []);
  const [promptRules, setPromptRules] = useState<PromptRule[]>(demoMode ? demoPrompts : []);
  const [credentials, setCredentials] = useState<PlatformCredential[]>(demoMode ? demoCredentials : []);
  const [optimizerTasks, setOptimizerTasks] = useState<OptimizerTask[]>(demoMode ? demoTasks : []);
  const [loading, setLoading] = useState(!demoMode);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    if (demoMode || !isAuthenticated()) {
      setLoading(false);
      return;
    }

    try {
      setLoading(true);
      setError(null);

      const [articlesRes, seriesRes, promptsRes, credsRes, optTasksRes] = await Promise.allSettled([
        searchArticles({ limit: 100 }),
        // Fetch series with entries (getSeries returns SeriesWithEntries)
        listSeries().then(async (seriesList) => {
          const enrichedSeries = await Promise.all(
            seriesList.map(async (s) => {
              try {
                const fullSeries = await getSeries(s.id);
                return fullSeries;
              } catch {
                return s;
              }
            })
          );
          return enrichedSeries;
        }),
        listPrompts(),
        listCredentials(),
        listOptimizerTasks(),
      ]);

      if (articlesRes.status === 'fulfilled') {
        const articlesData = articlesRes.value;
        // searchArticles returns ArticleRead[] directly
        if (Array.isArray(articlesData)) {
          setArticles(articlesData.map(mapArticleFromApi));
        }
      }
      if (seriesRes.status === 'fulfilled') {
        setSeriesList(seriesRes.value.map(mapSeriesFromApi));
      }
      if (promptsRes.status === 'fulfilled') {
        setPromptRules(promptsRes.value.map(mapPromptRuleFromApi));
      }
      if (credsRes.status === 'fulfilled') {
        setCredentials(credsRes.value.map(mapCredentialFromApi));
      }
      if (optTasksRes.status === 'fulfilled') {
        setOptimizerTasks(optTasksRes.value.map(mapOptimizerTaskFromApi));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isLoggedIn) {
      fetchData();
    }
  }, [fetchData, isLoggedIn]);

  const dashboardStats = {
    articleCount: articles.length,
    seriesCount: seriesList.length,
    failedPublishes: articles.flatMap((a) => a.publications || []).filter((p) => p.status === 'Failed').length,
    activeBlockers: articles.flatMap((a) => a.qualityIssues || []).filter((qi) => qi.severity === 'Block' && !qi.fixed).length,
    activeWarnings: articles.flatMap((a) => a.qualityIssues || []).filter((qi) => qi.severity === 'Critical_Warning' && !qi.fixed).length,
    promptEfficiency: '96.2%',
    overallProgress: 82,
  };

  return {
    articles,
    setArticles,
    seriesList,
    promptRules,
    setPromptRules,
    credentials,
    setCredentials,
    optimizerTasks,
    setOptimizerTasks,
    dashboardStats,
    loading,
    error,
    refresh: fetchData,
  };
}
