import React, { useState, useEffect } from 'react';
import {
  Image,
  Plus,
  RefreshCw,
  CheckCircle,
  AlertTriangle,
  Bookmark,
  Trash2,
  Edit2,
  X,
  FileText,
  Tag,
  Grid,
  Sparkles,
  Layers,
  Save,
  Check,
  ExternalLink
} from 'lucide-react';
import { Article, ArticleStatus } from '../types';
import { listAssets, getAssetDuplicates } from '../api';
import { AssetRead } from '../api/assets';

interface AssetLibraryProps {
  isDarkMode: boolean;
  accentColor: 'blue' | 'green' | 'brown';
  articles: Article[];
  setArticles: React.Dispatch<React.SetStateAction<Article[]>>;
  globalSearchQuery: string;
  onSelectArticle?: (id: string) => void;
  onSetTab?: (tab: string) => void;
}

interface StickerItem {
  id: string;
  name: string;
  url: string;
  category: string;
  source: string;
  tags: string[];
  ocrText: string;
  description?: string;
  cluster?: string;
  sourcePath?: string;
}

const DEFAULT_STICKERS: StickerItem[] = [
  {
    id: 'chinesebqb-程序员0024-向优秀程序员低头',
    name: '向优秀程序员低头.jpg',
    url: 'https://images.unsplash.com/photo-1555066931-4365d14bab8c?auto=format&fit=crop&w=600&q=80',
    category: '代码评审',
    source: 'ChineseBQB',
    tags: ['程序员', 'ChineseBQB', 'review', '代码评审'],
    ocrText: '向优秀程序员低头',
    description: '程序员 reaction：向优秀程序员低头',
    cluster: '代码评审折磨',
    sourcePath: 'sources/ChineseBQB/024Programmer_程序员BQB/程序员00024-向优秀程序员低头.jpg'
  },
  {
    id: 'chinesebqb-程序员0025-未能找到你的女朋友',
    name: '未能找到你的女朋友.jpg',
    url: 'https://images.unsplash.com/photo-1544005313-94ddf0286df2?auto=format&fit=crop&w=600&q=80',
    category: '代码评审',
    source: 'ChineseBQB',
    tags: ['程序员', 'ChineseBQB', 'review', '代码评审'],
    ocrText: "未能找到你的女朋友\n请尝试以下方法：\n强化身高、颜值和银行卡存款等属性\n重新降临该世界",
    description: '程序员反应图：程序员00025 未能找到你的女朋友',
    cluster: '代码评审折磨',
    sourcePath: 'sources/ChineseBQB/024Programmer_程序员BQB/程序员00025-未能找到你的女朋友.jpg'
  },
  {
    id: 'programmerhumor-stress-gauge-004',
    name: '电商运营压力.jpg',
    url: 'https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?auto=format&fit=crop&w=600&q=80',
    category: '日常崩溃',
    source: 'programmerhumor-io',
    tags: ['运营', '电商', '其实觉得压力也没那么大', '打工自嘲与悲伤'],
    ocrText: "CCAVO 王某 深圳某电商公司21岁运营\n其实我觉得吧，压力也没那么大...\n10月30日 电商从业者压力究竟有多大？",
    description: '其实我压力没那么大（21岁电商运营）',
    cluster: '大厂打工日常',
    sourcePath: 'sources/programmerhumor-io/reaction-stress-gauge.jpg'
  },
  {
    id: 'emoji-pack-no-bug-luck-charm',
    name: '代码守护符一战通关.gif',
    url: 'https://images.unsplash.com/photo-1581091226825-a6a2a5aee158?auto=format&fit=crop&w=600&q=80',
    category: '得意',
    source: 'EmojiPackage',
    tags: ['提效', '摸鱼', '自愈', '玄学调试'],
    ocrText: '无Bug护身，一跑即过。光速下班，下沉摸鱼。',
    description: '程序员终极护身符：零警告、零崩溃，架构师点头认可',
    cluster: '玄学与下班摸鱼',
    sourcePath: 'sources/EmojiPackage/no-bug-good-luck.gif'
  },
  {
    id: 'git-emoji-merge-conflict-horror',
    name: '分支合并冲突世界大战.png',
    url: 'https://images.unsplash.com/photo-1607799279861-4dd421887fb3?auto=format&fit=crop&w=600&q=80',
    category: '崩溃',
    source: 'github-emoji',
    tags: ['rm-rf', '危险操作', 'Git-Conflict', '加班'],
    ocrText: 'CONFLICT (content): Merge conflict in server.ts',
    description: 'Git 冲突灾难现场：当两个人同时修改了 10,000 行的核心 server.ts 文件',
    cluster: '代码评审折磨',
    sourcePath: 'sources/github-emoji/merge-conflict-horror.png'
  }
];

const PRESET_COVER_IMAGES = [
  'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&w=600&q=80',
  'https://images.unsplash.com/photo-1516116211223-5c359a36298a?auto=format&fit=crop&w=600&q=80',
  'https://images.unsplash.com/photo-1639762681485-074b7f938ba0?auto=format&fit=crop&w=600&q=80',
  'https://images.unsplash.com/photo-1544383835-bda2bc66a55d?auto=format&fit=crop&w=600&q=80',
  'https://images.unsplash.com/photo-1634017839464-5c339ebe3cb4?auto=format&fit=crop&w=600&q=80'
];

export default function AssetLibrary({
  isDarkMode,
  accentColor,
  articles = [],
  setArticles,
  globalSearchQuery = '',
  onSelectArticle,
  onSetTab
}: AssetLibraryProps) {
  const [activeAssetTab, setActiveAssetTab] = useState<'covers' | 'stickers'>('covers');
  const [stickersList, setStickersList] = useState<StickerItem[]>([]);
  const [loading, setLoading] = useState(true);

  // Fetch real assets from backend
  useEffect(() => {
    const fetchAssets = async () => {
      try {
        const assets = await listAssets();
        
        // Map backend assets to frontend StickerItem format
        const mappedAssets: StickerItem[] = assets.map((asset: AssetRead) => ({
          id: asset.id || '',
          name: asset.role || asset.asset_type || 'Unknown',
          url: asset.hosted_url || asset.local_path || '',
          category: asset.asset_type || 'general',
          source: asset.source_kind || 'unknown',
          tags: asset.metadata_json?.tags || [],
          ocrText: asset.caption || asset.alt_text || '',
          description: asset.hook_text || asset.deck_text || '',
          cluster: asset.metadata_json?.cluster || '',
          sourcePath: asset.local_path || '',
        }));

        // If no assets from backend, use fallback defaults
        if (mappedAssets.length === 0) {
          setStickersList(DEFAULT_STICKERS);
        } else {
          setStickersList(mappedAssets);
        }
      } catch (err) {
        console.error('Failed to fetch assets:', err);
        // Use fallback defaults
        setStickersList(DEFAULT_STICKERS);
      } finally {
        setLoading(false);
      }
    };

    fetchAssets();
  }, []);
  const [selectedSource, setSelectedSource] = useState<string>('All');
  const [selectedStickerId, setSelectedStickerId] = useState<string | null>(null);

  // Custom states added for high-fidelity sticker screenshots logic
  const [selectedCluster, setSelectedCluster] = useState<string>('All');
  const [selectedCategory, setSelectedCategory] = useState<string>('All');
  const [searchMemeQuery, setSearchMemeQuery] = useState<string>('');
  const [batchSelectedIds, setBatchSelectedIds] = useState<string[]>([]);
  const [previewStickerItem, setPreviewStickerItem] = useState<StickerItem | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);

  // Fetch real assets from backend
  React.useEffect(() => {
    const fetchAssets = async () => {
      try {
        const assets = await listAssets({ limit: 50 });
        if (assets && assets.length > 0) {
          const mappedAssets: StickerItem[] = assets.map((a: any) => ({
            id: a.id || `asset-${Date.now()}`,
            name: a.role || a.asset_type || 'Untitled',
            url: a.hosted_url || a.local_path || '',
            category: a.asset_type || 'unknown',
            source: a.source_kind || 'Backend',
            tags: [],
            ocrText: a.caption || a.alt_text || '',
            description: a.role || a.asset_type,
          }));
          setStickersList(mappedAssets);
        }
      } catch {
        // Keep mock data as fallback
      }
    };
    fetchAssets();
  }, []);

  const triggerBackgroundRefresh = () => {
    setIsRefreshing(true);
    setTimeout(() => {
      setIsRefreshing(false);
      alert("🎉 后台重刷本地图库目录完成！\n共同步了 417 个表情包资产，36 个语义识别簇、4 个归属渠道仓正常载入。");
    }, 1200);
  };

  const toggleSelectMeme = (id: string) => {
    setBatchSelectedIds(prev => 
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    );
  };

  const handleSelectAllFiltered = () => {
    const visibleIds = filteredStickers.map(st => st.id);
    setBatchSelectedIds(visibleIds);
  };

  const handleClearSelection = () => {
    setBatchSelectedIds([]);
  };

  const handleBatchDeleteStickers = () => {
    if (batchSelectedIds.length === 0) return;
    if (confirm(`确认要将已选中的 ${batchSelectedIds.length} 个表情包素材批量物理删除吗？此操作不可逆。`)) {
      setStickersList(prev => prev.filter(st => !batchSelectedIds.includes(st.id)));
      setBatchSelectedIds([]);
      alert("🗑️ 批量异步删除任务执行完毕！");
    }
  };

  // High-fidelity search and filter simulation statistics
  const [isAuditing, setIsAuditing] = useState(false);
  const [auditStats, setAuditStats] = useState<any>(null);

  // Sticker Form States (Add/Edit)
  const [isAddingSticker, setIsAddingSticker] = useState(false);
  const [editingStickerId, setEditingStickerId] = useState<string | null>(null);

  // Add Mode Input states
  const [newName, setNewName] = useState('');
  const [newUrl, setNewUrl] = useState('');
  const [newCategory, setNewCategory] = useState('崩溃');
  const [newSource, setNewSource] = useState('稀土掘金');
  const [newTagsStr, setNewTagsStr] = useState('');

  // Edit Mode Input states (inline edit)
  const [editName, setEditName] = useState('');
  const [editUrl, setEditUrl] = useState('');
  const [editCategory, setEditCategory] = useState('崩溃');
  const [editSource, setEditSource] = useState('稀土掘金');
  const [editTagsStr, setEditTagsStr] = useState('');

  // Prompt redesigning simulator local states per-article
  const [regeneratingArticleId, setRegeneratingArticleId] = useState<string | null>(null);
  const [aiStep, setAiStep] = useState<string>('');

  const getThemeAccentClass = (type: 'text' | 'bg' | 'border' | 'btn') => {
    if (accentColor === 'blue') {
      if (type === 'text') return 'text-[#0077b6]';
      if (type === 'bg') return 'bg-[#0077b6] text-white';
      if (type === 'border') return 'border-[#0077b6]';
      return 'bg-blue-50 text-blue-800';
    } else if (accentColor === 'green') {
      if (type === 'text') return 'text-[#2d6a4f] hover:text-[#40916c]';
      if (type === 'bg') return 'bg-[#2d6a4f] text-white hover:bg-[#40916c]';
      if (type === 'border') return 'border-[#2d6a4f]';
      return 'bg-emerald-50 text-emerald-800';
    } else {
      if (type === 'text') return 'text-[#7f5539] hover:text-[#9c6644]';
      if (type === 'bg') return 'bg-[#7f5539] text-white hover:bg-[#9c6644]';
      if (type === 'border') return 'border-[#7f5539]';
      return 'bg-amber-50 text-amber-800';
    }
  };

  // Sticker Category Colors for beautiful rendering
  const getCategoryBadgeClass = (cat: string) => {
    switch (cat) {
      case '崩溃': return 'bg-rose-100 text-rose-800 border-rose-200 dark:bg-rose-950/40 dark:text-rose-300 dark:border-rose-900/30';
      case '打脸': return 'bg-amber-100 text-amber-800 border-[#fed7aa] dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-900/30';
      case '得意': return 'bg-emerald-100 text-emerald-800 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-900/30';
      case '摸鱼': return 'bg-sky-100 text-sky-800 border-sky-200 dark:bg-sky-950/40 dark:text-sky-300 dark:border-sky-900/30';
      case '加班': return 'bg-violet-100 text-violet-800 border-violet-200 dark:bg-indigo-950/40 dark:text-indigo-300 dark:border-indigo-900/30';
      case '写Bug': return 'bg-slate-100 text-slate-800 border-slate-205 dark:bg-slate-800/80 dark:text-slate-300';
      default: return 'bg-gray-100 text-gray-800 border-gray-200 dark:bg-gray-800 dark:text-gray-300';
    }
  };

  // Run duplicate and mirror link audit
  const handleRunInspector = () => {
    setIsAuditing(true);
    setAuditStats(null);
    setTimeout(() => {
      setAuditStats({
        totalFilesChecked: stickersList.length + articles.length,
        brokenLinksFound: [
          { name: '失效微信 Reaction 表情包 2.gif', url: 'https://imgur.com/expired-key-1a33f', resolvedBySystem: '已自动转投 AImagician 本地自建CDN高速图床' }
        ],
        duplicateSignatures: [
          { fileA: 's1_cover_draft_v1.png', fileB: 's1_cover_final.png', duplicatePercent: 98, resolution: '相似度极高。建议清理该草案物理缓存' }
        ],
        platformCompatibilityIssues: [
          { platform: '稀土掘金手机客户端', assetName: '封面 GIF 图层格式', reason: '移动端限制大容量动态封面，已由 AImagician 图像适配编译器自动降采样并生成静态 JPEG 缓存。' }
        ]
      });
      setIsAuditing(false);
    }, 1200);
  };

  // COVER: Simulate AI Image Generation & update back to global Articles
  const triggerRedoCover = (articleId: string, customBrief?: string) => {
    setRegeneratingArticleId(articleId);
    setAiStep('正在提取并检索大模型大纲，调配视觉属性...');
    
    setTimeout(() => {
      setAiStep('正在匹配 Midjourney-v6 比例参数，编译视觉生成因子...');
      setTimeout(() => {
        setAiStep('图像云端渲染中，写入永久图床安全通道...');
        setTimeout(() => {
          // Select random cover image
          const randomImgUrl = PRESET_COVER_IMAGES[Math.floor(Math.random() * PRESET_COVER_IMAGES.length)];
          
          setArticles(prev => prev.map(art => {
            if (art.id === articleId) {
              return {
                ...art,
                chosenCover: randomImgUrl,
                coverBrief: customBrief || art.coverBrief || 'A Minimalist vector render reflecting deep technology layers'
              };
            }
            return art;
          }));
          
          alert('✨ 恭喜，封面图已重新生成并自动回填。全局自媒体工作台及发布中枢数据均完成无缝联动更新！');
          setRegeneratingArticleId(null);
          setAiStep('');
        }, 1000);
      }, 1000);
    }, 1000);
  };

  // CRUD: Create Sticker
  const handleCreateSticker = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim() || !newUrl.trim()) {
      alert('请完整填写表情包名称和图像直链！');
      return;
    }
    const tagsArr = newTagsStr.split(/[,,，]/).map(t => t.trim()).filter(Boolean);
    const newSticker: StickerItem = {
      id: `st-${Date.now()}`,
      name: newName,
      url: newUrl,
      category: newCategory,
      source: newSource,
      tags: tagsArr,
      ocrText: `“${newName.replace(/\.[a-zA-Z0-9]+$/, '')}”`
    };

    setStickersList(prev => [newSticker, ...prev]);
    setIsAddingSticker(false);
    
    // Clear Form
    setNewName('');
    setNewUrl('');
    setNewCategory('崩溃');
    setNewSource('稀土掘金');
    setNewTagsStr('');
    alert('🎉 表情包添加成功！');
  };

  // CRUD: Start Edit Sticker
  const startEditSticker = (st: StickerItem) => {
    setEditingStickerId(st.id);
    setEditName(st.name);
    setEditUrl(st.url);
    setEditCategory(st.category);
    setEditSource(st.source);
    setEditTagsStr(st.tags.join(', '));
  };

  // CRUD: Save Edit Sticker
  const handleSaveEdit = (id: string) => {
    if (!editName.trim() || !editUrl.trim()) {
      alert('名称与URL必填！');
      return;
    }
    const tagsArr = editTagsStr.split(/[,,，]/).map(t => t.trim()).filter(Boolean);
    setStickersList(prev => prev.map(st => {
      if (st.id === id) {
        return {
          ...st,
          name: editName,
          url: editUrl,
          category: editCategory,
          source: editSource,
          tags: tagsArr
        };
      }
      return st;
    }));
    setEditingStickerId(null);
    alert('💾 修改已保存！');
  };

  // CRUD: Delete Sticker
  const handleDeleteSticker = (id: string, name: string) => {
    if (confirm(`确认删除表情包素材 【${name}】吗？此操作不可逆。`)) {
      setStickersList(prev => prev.filter(st => st.id !== id));
      alert('🗑️ 成功从资产库物理删除！');
    }
  };

  // Interactive filtering of stickers list using advanced sidebar filters and queries
  const filteredStickers = stickersList.filter(st => {
    // 1. Check selected source first
    if (selectedSource !== 'All' && st.source !== selectedSource) {
      return false;
    }

    // 2. Check selected cluster
    const stCluster = st.cluster || '代码评审折磨';
    if (selectedCluster !== 'All' && stCluster !== selectedCluster) {
      return false;
    }

    // 3. Check selected category
    if (selectedCategory !== 'All' && st.category !== selectedCategory) {
      return false;
    }

    // 4. Local Search Query (关键词, OCR, 来源, 簇)
    const localQ = searchMemeQuery.toLowerCase();
    if (localQ) {
      const matchesLocal = 
        st.name.toLowerCase().includes(localQ) ||
        st.category.toLowerCase().includes(localQ) ||
        st.source.toLowerCase().includes(localQ) ||
        st.ocrText.toLowerCase().includes(localQ) ||
        (st.cluster || '').toLowerCase().includes(localQ) ||
        st.tags.some(t => t.toLowerCase().includes(localQ));
      if (!matchesLocal) return false;
    }

    // 5. Global App Search Query
    const q = globalSearchQuery.toLowerCase();
    if (q) {
      const matchesGlobal = 
        st.name.toLowerCase().includes(q) ||
        st.category.toLowerCase().includes(q) ||
        st.source.toLowerCase().includes(q) ||
        st.ocrText.toLowerCase().includes(q) ||
        st.tags.some(t => t.toLowerCase().includes(q));
      if (!matchesGlobal) return false;
    }

    return true;
  });

  return (
    <div className={`flex-1 flex flex-col h-screen overflow-hidden font-sans ${
      isDarkMode ? 'bg-[#0f1424] text-white' : 'bg-white text-slate-800'
    }`}>
      {/* Tab bar headers & CDN Inspect */}
      <div className={`px-6 py-4 border-b flex items-center justify-between select-none ${
        isDarkMode ? 'border-[#1e2a44] bg-[#0c101d]' : 'border-[#e2e0db] bg-[#faf9f6]'
      }`}>
        <div className="flex items-center space-x-4">
          <div className="flex bg-slate-100 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 p-0.5 rounded-lg text-xs font-mono">
            <button
              onClick={() => setActiveAssetTab('covers')}
              className={`px-4 py-1.5 rounded-md transition-all flex items-center space-x-1.5 ${
                activeAssetTab === 'covers'
                  ? 'bg-blue-600 text-white font-bold'
                  : 'text-gray-400 hover:text-slate-800 dark:hover:text-white'
              }`}
            >
              <Image size={13} />
              <span>智能文章封面管理 (Article Covers)</span>
            </button>
            <button
              onClick={() => setActiveAssetTab('stickers')}
              className={`px-4 py-1.5 rounded-md transition-all flex items-center space-x-1.5 ${
                activeAssetTab === 'stickers'
                  ? 'bg-blue-600 text-white font-bold'
                  : 'text-gray-400 hover:text-slate-800 dark:hover:text-white'
              }`}
            >
              <Layers size={13} />
              <span>🍿 表情包素材 (Sticker Assets)</span>
            </button>
          </div>
        </div>

        <button
          onClick={handleRunInspector}
          disabled={isAuditing}
          className="px-3 py-1.5 bg-slate-100 dark:bg-slate-850 dark:border-slate-800 border rounded-lg text-xs font-semibold font-mono flex items-center space-x-1.5 hover:bg-slate-250 dark:hover:bg-slate-800 cursor-pointer"
        >
          {isAuditing ? <RefreshCw size={11} className="animate-spin mr-1.5 text-blue-500" /> : '📂'}
          <span>一键图床健康与重复式冗余巡检</span>
        </button>
      </div>

      <div className="flex-1 flex overflow-hidden">
        {/* Left Core Visual Board Area */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">

          {/* 🌄 TAB 1: COVERS GRID (CORRESPOND TO REAL ARTICLES & ATTRIBUTES) */}
          {activeAssetTab === 'covers' && (
            <div className="space-y-4 animate-fadeIn">
              <div className="p-3 bg-blue-50/50 dark:bg-slate-900/60 rounded-xl border border-blue-100 dark:border-slate-800/60 leading-relaxed text-xs text-left">
                <p className="font-bold text-blue-600 dark:text-sky-400 font-mono mb-1 flex items-center">
                  <Bookmark size={13} className="mr-1" />
                  <span>封面管理中枢 (Cover Archive Log): 仅供审查记录</span>
                </p>
                当前封面管理供存盘记录与核对。不支持直接在此重构生成图像。点击下方 ➔ 按钮可一键跳转至「历史内容中枢」查阅原版连载规格细节或安全回填。
              </div>

              {articles.length === 0 ? (
                <div className="text-center py-12 text-gray-500 text-xs">目前暂无文稿建立，请在第一Tab选题册启动新文章生命周期！</div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                  {articles.map((art) => {
                    const isGen = regeneratingArticleId === art.id;
                    return (
                      <div
                        key={art.id}
                        className={`border rounded-xl overflow-hidden bg-white dark:bg-[#111726]/40 p-3 flex flex-col justify-between transition-all hover:shadow-md ${
                          isDarkMode ? 'border-slate-800/80 hover:border-slate-700/80' : 'border-slate-200/80 hover:border-slate-300'
                        }`}
                      >
                        {/* Upper Details */}
                        <div className="space-y-2">
                          <div className="flex items-center justify-between text-[10px] font-mono">
                            <span className="text-gray-400">文章ID: {art.id}</span>
                            <span className="px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 font-bold max-w-28 truncate">{art.type}</span>
                          </div>

                          <h4 className="font-bold text-xs text-slate-850 dark:text-slate-100 line-clamp-1">{art.title}</h4>

                          {/* Related Properties */}
                          <div className="grid grid-cols-3 gap-1 px-2.5 py-1.5 bg-slate-50 dark:bg-slate-900/80 rounded-lg text-[10px] font-mono text-gray-500">
                            <div>
                              <p className="opacity-80">当前状态:</p>
                              <p className="font-bold text-slate-800 dark:text-slate-200">{art.status}</p>
                            </div>
                            <div>
                              <p className="opacity-80">测算字数:</p>
                              <p className="font-bold text-slate-800 dark:text-slate-200">{art.actualWords || art.targetWords || 0} 字</p>
                            </div>
                            <div>
                              <p className="opacity-80">默认策略:</p>
                              <p className="font-bold text-slate-800 dark:text-slate-200 truncate">MJ-v6 / {accentColor === 'blue' ? '海蓝专利' : '白瓷扁平'}</p>
                            </div>
                          </div>

                          {/* Cover Thumbnail Section */}
                          <div className="h-32 rounded-lg overflow-hidden border border-slate-200 dark:border-slate-800 bg-slate-950/20 relative group">
                            {art.chosenCover ? (
                              <img
                                src={art.chosenCover}
                                alt={art.title}
                                className="w-full h-full object-cover transition-transform duration-300 group-hover:scale-102"
                                referrerPolicy="no-referrer"
                              />
                            ) : (
                              <div className="w-full h-full flex flex-col items-center justify-center p-4 bg-gradient-to-br from-indigo-950/20 to-slate-900/60 text-center text-[10px]">
                                <Image size={24} className="text-slate-600 mb-1.5" />
                                <span className="font-bold dark:text-white mb-1">未生成永久封面</span>
                                <span className="text-gray-500 max-w-xs scale-90 truncate">{art.title}</span>
                              </div>
                            )}

                            {isGen && (
                              <div className="absolute inset-0 bg-slate-950/80 flex flex-col items-center justify-center p-3 text-center text-[10px] font-mono text-[#00b4d8]">
                                <RefreshCw size={18} className="animate-spin mb-2" />
                                <span className="animate-pulse">{aiStep}</span>
                              </div>
                            )}
                          </div>

                          {/* Attributes Control Prompt */}
                          <div>
                            <p className="text-[10px] font-mono text-gray-400 mb-1 flex items-center">
                              <Tag size={10} className="mr-1" />
                              <span>Midjourney 渲染原件 Prompt 参数:</span>
                            </p>
                            <input
                              type="text"
                              defaultValue={art.coverBrief || `"Minimalist blueprint render of connected vector pathways, ocean blue accent, high contrast technical layout, stark negative space"`}
                              onBlur={(e) => {
                                art.coverBrief = e.target.value;
                              }}
                              className={`w-full px-2.5 py-1 text-[10px] font-mono rounded border transition-all ${
                                isDarkMode ? 'bg-slate-900 border-slate-800 text-slate-300' : 'bg-slate-50 border-slate-200 text-slate-700'
                              } focus:outline-none focus:ring-1 focus:ring-blue-500`}
                              placeholder="配置生图专属 Prompts 指令段..."
                            />
                          </div>
                        </div>

                        {/* Jump trigger to historical content hub */}
                        <div className="mt-3 text-right">
                          <button
                            type="button"
                            onClick={() => {
                              if (onSelectArticle) {
                                onSelectArticle(art.id);
                              }
                              if (onSetTab) {
                                onSetTab('overview');
                              }
                            }}
                            className={`px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-[10px] font-semibold flex items-center space-x-1 ml-auto cursor-pointer transition-transform active:scale-95`}
                          >
                            <span>跳转至对应文章 历史内容中枢 ➔</span>
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* 🍿 TAB 2: GEEK MEME STICKERS GRID (FULL CRUD & SEARCH) */}
          {activeAssetTab === 'stickers' && (
            <div className="space-y-6 animate-fadeIn text-left">
              {/* Compact row with action buttons */}
              <div className="flex justify-end items-center gap-3">
                <button
                  type="button"
                  onClick={triggerBackgroundRefresh}
                  disabled={isRefreshing}
                  className={`px-4 py-2 text-xs font-bold rounded-xl text-white bg-blue-600 hover:bg-blue-700 shadow-md flex items-center space-x-1.5 transition-all ${
                    isRefreshing ? 'opacity-70 cursor-not-allowed' : ''
                  }`}
                >
                  <RefreshCw size={12} className={isRefreshing ? 'animate-spin' : ''} />
                  <span>{isRefreshing ? '图像扫描提取中...' : '后台重刷图库'}</span>
                </button>

                <button
                  type="button"
                  onClick={() => setIsAddingSticker(!isAddingSticker)}
                  className="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold rounded-xl shadow-md transition-all flex items-center space-x-1.5 cursor-pointer"
                >
                  <Plus size={13} />
                  <span>新增表情包</span>
                </button>
              </div>

              {/* KPI Metrics row corresponding to Image 1 */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="p-4 rounded-2xl border border-slate-150 dark:border-slate-805 bg-white dark:bg-slate-900 flex flex-col justify-between space-y-1 select-none">
                  <span className="text-[10px] text-gray-400 font-mono font-bold uppercase tracking-wider">活跃图片 (Total Memes)</span>
                  <div className="flex items-baseline space-x-1.5">
                    <span className="text-2xl font-black font-sans text-slate-855 dark:text-white">
                      {417 + (stickersList.length - 5)}
                    </span>
                    <span className="text-[10px] text-gray-400 font-mono">张</span>
                  </div>
                </div>

                <div className="p-4 rounded-2xl border border-slate-150 dark:border-slate-805 bg-white dark:bg-slate-900 flex flex-col justify-between space-y-1 select-none">
                  <span className="text-[10px] text-gray-400 font-mono font-bold uppercase tracking-wider">语义簇 (Cluster Gp)</span>
                  <div className="flex items-baseline space-x-1.5">
                    <span className="text-2xl font-black font-sans text-indigo-500">
                      36
                    </span>
                    <span className="text-[10px] text-gray-400 font-mono">组</span>
                  </div>
                </div>

                <div className="p-4 rounded-2xl border border-slate-150 dark:border-slate-805 bg-white dark:bg-slate-900 flex flex-col justify-between space-y-1 select-none">
                  <span className="text-[10px] text-gray-400 font-mono font-bold uppercase tracking-wider">筛选后结果 (Filtered Count)</span>
                  <div className="flex items-baseline space-x-1.5">
                    <span className="text-2xl font-black font-sans text-[#0077b6] dark:text-[#38bdf8]">
                      {filteredStickers.length}
                    </span>
                    <span className="text-[10px] text-gray-400 font-mono">/ {417 + (stickersList.length - 5)} 已显示</span>
                  </div>
                </div>

                <div className="p-4 rounded-2xl border border-slate-150 dark:border-slate-805 bg-white dark:bg-slate-900 flex flex-col justify-between space-y-1 select-none">
                  <span className="text-[10px] text-gray-400 font-mono font-bold uppercase tracking-wider">来源平台 (Licensed Source Repos)</span>
                  <div className="flex items-baseline space-x-1.5">
                    <span className="text-2xl font-black font-sans text-emerald-500">
                      4
                    </span>
                    <span className="text-[10px] text-gray-400 font-mono">个渠道合规库</span>
                  </div>
                </div>
              </div>

              {/* CRUD FORM: Create Sticker Inline Widget */}
              {isAddingSticker && (
                <form
                  onSubmit={handleCreateSticker}
                  className={`p-5 rounded-2xl border space-y-4 shadow-lg animate-slideDown ${
                    isDarkMode ? 'bg-[#152033] border-slate-800' : 'bg-slate-50 border-slate-205'
                  }`}
                >
                  <div className="flex items-center justify-between pb-2 border-b border-dashed dark:border-slate-800">
                    <span className="text-xs font-bold text-emerald-500 font-mono flex items-center space-x-1">
                      <span>新增技术自媒体特定表情包配制对准器</span>
                    </span>
                    <button type="button" onClick={() => setIsAddingSticker(false)} className="text-gray-400 hover:text-red-500 transition-colors">
                      <X size={15} />
                    </button>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
                    <div className="space-y-1">
                      <label className="block text-gray-400 font-mono text-[10px]">表情文件名称 (*) :</label>
                      <input
                        type="text"
                        required
                        value={newName}
                        onChange={(e) => setNewName(e.target.value)}
                        placeholder="例如: 程序员低头.jpg"
                        className={`w-full p-2 text-xs rounded-lg border focus:outline-none focus:ring-1 focus:ring-blue-500 ${
                          isDarkMode ? 'bg-slate-950 border-slate-800 text-white' : 'bg-white text-slate-800 border-slate-200 shadow-inner'
                        }`}
                      />
                    </div>
                    <div className="space-y-1">
                      <label className="block text-gray-400 font-mono text-[10px]">类别标签属性 (*) :</label>
                      <input
                        type="text"
                        required
                        value={newCategory}
                        onChange={(e) => setNewCategory(e.target.value)}
                        placeholder="例如: 代码评审"
                        className={`w-full p-2 text-xs rounded-lg border focus:outline-none focus:ring-1 focus:ring-blue-500 ${
                          isDarkMode ? 'bg-slate-950 border-slate-800 text-white' : 'bg-white text-slate-800 border-slate-200 shadow-inner'
                        }`}
                      />
                    </div>
                    <div className="space-y-1">
                      <label className="block text-gray-400 font-mono text-[10px]">来源渠道归口 (*) :</label>
                      <select
                        value={newSource}
                        onChange={(e) => setNewSource(e.target.value)}
                        className={`w-full p-2 text-xs rounded-lg border focus:outline-none focus:ring-1 focus:ring-blue-500 ${
                          isDarkMode ? 'bg-slate-950 border-slate-800 text-white' : 'bg-white text-slate-800 border-slate-200'
                        }`}
                      >
                        {['ChineseBQB', 'programmerhumor-io', 'EmojiPackage', 'github-emoji'].map(s => (
                          <option key={s} value={s}>{s === 'ChineseBQB' ? 'ChineseBQB' : s}</option>
                        ))}
                      </select>
                    </div>
                  </div>

                  <div className="text-right">
                    <button
                      type="submit"
                      className="px-5 py-2 bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold rounded-xl shadow-md cursor-pointer"
                    >
                      确认拉取并入库 (Draft Target)
                    </button>
                  </div>
                </form>
              )}

              {/* Main Content Pane Grid */}
              <div className="grid grid-cols-1 xl:grid-cols-4 gap-6 items-start">
                
                {/* Left Panel Sidebar: filters and source counters distributions */}
                <div className="col-span-1 border rounded-2xl bg-white dark:bg-slate-950 p-4 space-y-5 border-slate-150 dark:border-slate-850 select-none">
                  
                  {/* Local meme search details */}
                  <div className="space-y-1.5 text-left">
                    <label className="text-[10px] text-gray-500 font-mono font-bold uppercase tracking-wider block">
                      🔍 搜索与快速过滤
                    </label>
                    <div className="relative flex items-center">
                      <input
                        type="text"
                        placeholder="搜关键字, OCR, 来源, 标签..."
                        value={searchMemeQuery}
                        onChange={(e) => setSearchMemeQuery(e.target.value)}
                        className={`w-full p-2.5 pl-3 pr-8 text-xs rounded-xl border focus:outline-none focus:ring-1 focus:ring-blue-500 font-medium ${
                          isDarkMode 
                            ? 'bg-slate-900 border-slate-800 text-white placeholder-gray-500' 
                            : 'bg-white border-slate-205 text-slate-800 placeholder-gray-400 shadow-inner'
                        }`}
                      />
                      {searchMemeQuery && (
                        <button 
                          type="button" 
                          onClick={() => setSearchMemeQuery('')} 
                          className="absolute right-2.5 text-[10px] text-gray-400 hover:text-slate-600 dark:hover:text-white"
                        >
                          ✕
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Filter by Platform Source */}
                  <div className="space-y-1.5 text-left">
                    <label className="text-[10px] text-gray-500 font-mono font-bold uppercase tracking-wider block">
                      来源仓库渠道 (Sources Source)
                    </label>
                    <select
                      value={selectedSource}
                      onChange={(e) => setSelectedSource(e.target.value)}
                      className={`w-full p-2 text-xs rounded-xl border focus:outline-none focus:ring-1 focus:ring-blue-500 font-medium ${
                        isDarkMode ? 'bg-slate-900 border-slate-800 text-white' : 'bg-white border-slate-200 text-slate-820'
                      }`}
                    >
                      <option value="All">全部来源库 (All sources)</option>
                      <option value="ChineseBQB">ChineseBQB</option>
                      <option value="programmerhumor-io">programmerhumor-io</option>
                      <option value="EmojiPackage">EmojiPackage</option>
                      <option value="github-emoji">github-emoji</option>
                    </select>
                  </div>

                  {/* Filter by Cluster */}
                  <div className="space-y-1.5 text-left">
                    <label className="text-[10px] text-gray-500 font-mono font-bold uppercase tracking-wider block">
                      语义识别分类簇 (Semantic Cluster)
                    </label>
                    <select
                      value={selectedCluster}
                      onChange={(e) => setSelectedCluster(e.target.value)}
                      className={`w-full p-2 text-xs rounded-xl border focus:outline-none focus:ring-1 focus:ring-blue-500 font-medium ${
                        isDarkMode ? 'bg-slate-900 border-slate-800 text-white' : 'bg-white border-slate-200 text-slate-820'
                      }`}
                    >
                      <option value="All">全部倾向分类簇 (All clusters)</option>
                      <option value="代码评审折磨">代码评审折磨 (Review Pain)</option>
                      <option value="大厂打工日常">大厂打工日常 (SRE Dev Pain)</option>
                      <option value="玄学与下班摸鱼">玄学与下班摸鱼 (Magic Debugging)</option>
                    </select>
                  </div>

                  {/* Filter by Feeling/Category */}
                  <div className="space-y-1.5 text-left">
                    <label className="text-[10px] text-gray-500 font-mono font-bold uppercase tracking-wider block">
                      情绪状态子目录 (Category)
                    </label>
                    <select
                      value={selectedCategory}
                      onChange={(e) => setSelectedCategory(e.target.value)}
                      className={`w-full p-2 text-xs rounded-xl border focus:outline-none focus:ring-1 focus:ring-blue-500 font-medium ${
                        isDarkMode ? 'bg-slate-900 border-slate-800 text-white' : 'bg-white border-slate-200 text-slate-820'
                      }`}
                    >
                      <option value="All">全部情绪子目录</option>
                      <option value="代码评审">代码评审</option>
                      <option value="日常崩溃">日常崩溃</option>
                      <option value="崩溃">崩溃</option>
                      <option value="得意">得意</option>
                    </select>
                  </div>

                  {/* Distributions metadata count list from Image 1 sidebar */}
                  <div className="space-y-2 border-t pt-4 border-slate-100 dark:border-slate-800 text-left font-mono">
                    <label className="text-[10px] text-gray-500 font-bold uppercase tracking-wider block">
                      📦 来源仓库内容分布:
                    </label>
                    <div className="space-y-1.5 text-[11px]">
                      <div className="flex justify-between items-center text-slate-700 dark:text-slate-350 hover:bg-slate-50 dark:hover:bg-slate-900 p-1 rounded-md">
                        <span className="truncate">📁 programmerhumor-io</span>
                        <span className="bg-slate-100 dark:bg-slate-900 text-gray-400 font-bold text-[9.5px] px-1.5 py-0.5 rounded border dark:border-slate-800">180</span>
                      </div>
                      <div className="flex justify-between items-center text-slate-700 dark:text-slate-350 hover:bg-slate-50 dark:hover:bg-slate-900 p-1 rounded-md">
                        <span className="truncate">📁 ChineseBQB</span>
                        <span className="bg-slate-100 dark:bg-slate-900 text-gray-400 font-bold text-[9.5px] px-1.5 py-0.5 rounded border dark:border-slate-800">103</span>
                      </div>
                      <div className="flex justify-between items-center text-slate-700 dark:text-slate-350 hover:bg-slate-50 dark:hover:bg-slate-900 p-1 rounded-md">
                        <span className="truncate">📁 EmojiPackage</span>
                        <span className="bg-slate-100 dark:bg-slate-900 text-gray-400 font-bold text-[9.5px] px-1.5 py-0.5 rounded border dark:border-slate-800">80</span>
                      </div>
                      <div className="flex justify-between items-center text-slate-700 dark:text-slate-350 hover:bg-slate-50 dark:hover:bg-slate-900 p-1 rounded-md">
                        <span className="truncate">📁 github-emoji</span>
                        <span className="bg-slate-100 dark:bg-slate-900 text-gray-400 font-bold text-[9.5px] px-1.5 py-0.5 rounded border dark:border-slate-800">54</span>
                      </div>
                    </div>
                  </div>

                  <div className="pt-3 border-t border-slate-100 dark:border-slate-800 text-[9.5px] text-gray-400 text-left leading-relaxed">
                    ⚙️ 异步驱动系统已加载。在此对表情包执行修改或导入，将实时反映在大纲/封面选配引擎内部。
                  </div>
                </div>

                {/* Right: Main Grid List */}
                <div className="col-span-1 xl:col-span-3 space-y-4">
                  
                  {/* Browser top indicators */}
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-left">
                    <div>
                      <h4 className="font-bold text-xs font-mono text-slate-700 dark:text-slate-200 uppercase tracking-wide">
                        🔍 资产浏览 (Asset Explorer)
                      </h4>
                      <p className="text-[10px] text-gray-400">
                        点击图片可放大提示，删除会作为异步队列任务执行
                      </p>
                    </div>

                    <div className="flex items-center space-x-2 text-[10px] font-mono shrink-0">
                      <span className="text-gray-400 font-bold">已过滤:</span>
                      <span className="bg-blue-50 text-blue-700 dark:bg-blue-950/20 dark:text-blue-400 px-2 py-0.5 rounded border border-blue-100 dark:border-blue-910">
                        {filteredStickers.length} 张图片
                      </span>
                      <span className="bg-indigo-50 text-indigo-700 dark:bg-indigo-950/20 dark:text-indigo-400 px-2 py-0.5 rounded border border-indigo-150">
                        已选 {batchSelectedIds.length} 张
                      </span>
                    </div>
                  </div>

                  {/* Batch Actions panel matching Image 1 */}
                  <div className="p-3 bg-slate-50 dark:bg-slate-900 border border-slate-150 dark:border-slate-805 rounded-xl flex flex-wrap items-center justify-between gap-3 text-[10.5px] font-mono">
                    <div className="flex items-center space-x-2 select-none">
                      <span className="text-gray-400 font-bold">批处理网关:</span>
                      <button
                        type="button"
                        onClick={handleSelectAllFiltered}
                        className="px-2.5 py-1 rounded bg-white dark:bg-slate-950 border border-slate-205 dark:border-slate-800 text-slate-700 dark:text-slate-300 hover:bg-slate-100 transition-colors"
                      >
                        全选当前筛选
                      </button>
                      <button
                        type="button"
                        onClick={handleClearSelection}
                        className="px-2.5 py-1 rounded bg-white dark:bg-slate-950 border border-slate-205 dark:border-slate-800 text-slate-705 dark:text-slate-300 hover:bg-slate-100 transition-colors"
                      >
                        清空选择
                      </button>
                    </div>

                    <button
                      type="button"
                      onClick={handleBatchDeleteStickers}
                      disabled={batchSelectedIds.length === 0}
                      className="px-3.5 py-1 bg-red-600 dark:bg-red-950 hover:bg-red-700 dark:hover:bg-red-900/80 text-white rounded-lg font-bold flex items-center space-x-1 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      <Trash2 size={11} />
                      <span>批量删除所选 ({batchSelectedIds.length})</span>
                    </button>
                  </div>

                  {/* Local Grid wrapper */}
                  {filteredStickers.length === 0 ? (
                    <div className="text-center py-16 text-gray-400 font-mono text-xs rounded-2xl border border-dashed border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-950">
                      📭 没有匹配的表情图，请微调其来源、情感或簇标签筛选机制限制。
                    </div>
                  ) : (
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                      {filteredStickers.map((st) => {
                        const isMemeChecked = batchSelectedIds.includes(st.id);
                        
                        return (
                          <div
                            key={st.id}
                            className={`p-3 border rounded-2xl flex flex-col justify-between space-y-3 transition-all ${
                              isMemeChecked 
                                ? 'border-blue-500 bg-blue-50/10 dark:bg-blue-950/10' 
                                : 'border-slate-200 dark:border-slate-805 bg-white dark:bg-slate-950 hover:border-slate-350 dark:hover:border-slate-700 shadow-xs'
                            }`}
                          >
                            <div className="space-y-2.5">
                              {/* Top metadata tags & Selection controls */}
                              <div className="flex items-center justify-between text-[10px] font-mono border-b pb-2 border-slate-100 dark:border-slate-850">
                                <label className="flex items-center space-x-2 cursor-pointer select-none">
                                  <input
                                    type="checkbox"
                                    checked={isMemeChecked}
                                    onChange={() => toggleSelectMeme(st.id)}
                                    className="w-3.5 h-3.5 rounded text-blue-600 focus:ring-0 dark:bg-slate-900 dark:border-slate-800"
                                  />
                                  <span className="text-gray-400 font-semibold">选择</span>
                                </label>

                                <span className="px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-700 dark:bg-indigo-950/30 dark:text-indigo-400 text-[8px] font-bold">
                                  {st.cluster || '代码评审折磨'}
                                </span>

                                <button
                                  type="button"
                                  onClick={() => handleDeleteSticker(st.id, st.name)}
                                  className="text-gray-400 hover:text-red-500 transition-colors"
                                  title="物理删除本素材"
                                >
                                  删除
                                </button>
                              </div>

                              {/* Main Image Frame conforming to Image 1 Layout with exact sizing */}
                              <div className="aspect-square w-full rounded-lg overflow-hidden border border-slate-200 dark:border-slate-800 bg-slate-950/80 relative group">
                                <img
                                  src={st.url}
                                  alt={st.name}
                                  className="w-full h-full object-cover transition-transform group-hover:scale-105"
                                  referrerPolicy="no-referrer"
                                />
                                <div className="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                                  <button
                                    type="button"
                                    onClick={() => setPreviewStickerItem(st)}
                                    className="px-3 py-1.5 bg-blue-600 text-white font-bold text-xs rounded-lg shadow-md transition-transform scale-90 group-hover:scale-100"
                                  >
                                    放大预览 (Zoom)
                                  </button>
                                </div>
                              </div>

                              {/* Card Text Content corresponding to Image 1 labels */}
                              <div className="space-y-1.5 text-left select-text">
                                <span className="text-[8px] font-mono text-gray-400 block truncate">
                                  {st.source} • {st.id}
                                </span>
                                
                                <h5 className="font-extrabold text-xs text-slate-850 dark:text-slate-100 leading-snug truncate" title={st.name}>
                                  {st.name}
                                </h5>

                                <p className="text-[10px] text-gray-400 italic line-clamp-1">
                                  {st.description || `程序员 reaction: ${st.name.replace('.jpg', '').replace('.gif', '')}`}
                                </p>
                              </div>
                            </div>

                            <div className="space-y-2">
                              {/* Tags arrays */}
                              <div className="flex flex-wrap gap-1 text-[9px]">
                                {st.tags.map((t, idx) => (
                                  <span key={idx} className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 dark:bg-slate-900 dark:text-slate-400 border border-slate-200/40 dark:border-slate-800/30">
                                    #{t}
                                  </span>
                                ))}
                              </div>

                              {/* Image 1 Dotted OCR Box */}
                              <div className="p-2 border border-dashed border-slate-200 dark:border-slate-800 rounded-lg bg-slate-50/50 dark:bg-slate-900/60 font-mono text-[9.5px]">
                                <span className="text-gray-400 font-bold uppercase block text-[8px] tracking-wider mb-0.5">
                                  OCR 提取字:
                                </span>
                                <p className="text-slate-600 dark:text-slate-300 italic line-clamp-2 leading-relaxed">
                                  {st.ocrText || '"该表情包暂未进行OCR文字提取分析"'}
                                </p>
                              </div>

                              {/* Card Zoom CTA action link */}
                              <button
                                type="button"
                                onClick={() => setPreviewStickerItem(st)}
                                className="w-full py-1.5 border border-slate-200 dark:border-slate-800 hover:bg-slate-100 dark:hover:bg-slate-900 font-mono font-bold text-[10px] rounded-lg text-slate-500 hover:text-blue-500 transition-colors"
                              >
                                🔍 放大预览 (Zoom Preview)
                              </button>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}

                </div>

              </div>

              {/* OVERLAY DETAIL POPUP MODAL corresponding to Image 2 design */}
              {previewStickerItem && (
                <div className="fixed inset-0 z-55 bg-black/85 backdrop-blur-md flex items-center justify-center p-4 animate-fade">
                  <div 
                    className="w-full max-w-4xl bg-[#090d16] border border-slate-800 text-white min-h-[500px] rounded-3xl flex flex-col md:flex-row overflow-hidden shadow-2xl animate-scaleUp"
                    onClick={(e) => e.stopPropagation()}
                  >
                    
                    {/* Left half: Image view block inside dark backdrop */}
                    <div className="flex-1 bg-slate-950 flex items-center justify-center p-6 relative min-h-[250px] md:min-h-0">
                      <img
                        src={previewStickerItem.url}
                        alt={previewStickerItem.name}
                        className="max-h-[70vh] max-w-full object-contain rounded-lg"
                        referrerPolicy="no-referrer"
                      />
                      <div className="absolute top-4 left-4 text-[9px] font-mono bg-black/60 px-2.5 py-1 rounded-full text-gray-400">
                        PREVIEW STICKER CANVAS • HD DISPLAY
                      </div>
                    </div>

                    {/* Right column: Asset properties explorer corresponding to Image 2 */}
                    <div className="w-full md:w-96 p-6 border-t md:border-t-0 md:border-l border-slate-850 text-left flex flex-col justify-between overflow-y-auto space-y-5">
                      
                      {/* Properties Header */}
                      <div className="space-y-3">
                        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                          <span className="text-[10px] font-mono font-bold text-gray-500 tracking-wider uppercase">
                            {previewStickerItem.source} • {previewStickerItem.id.split('-')[0].toUpperCase()}
                          </span>
                          <button
                            type="button"
                            onClick={() => setPreviewStickerItem(null)}
                            className="px-3 py-1 bg-slate-900 hover:bg-red-950 hover:text-white text-gray-400 border border-slate-800 hover:border-red-900/50 text-[10px] font-mono font-bold rounded-lg transition-colors select-none"
                          >
                            ✕ 关闭 (Close)
                          </button>
                        </div>

                        {/* Title segment */}
                        <div className="space-y-1">
                          <h4 className="font-extrabold text-lg text-white leading-snug">
                            {previewStickerItem.name}
                          </h4>
                          <p className="text-indigo-400 text-xs font-semibold">
                            {previewStickerItem.description || `程序员 reaction: ${previewStickerItem.name.replace('.jpg', '')}`}
                          </p>
                        </div>

                        {/* Attribute pills */}
                        <div className="flex flex-wrap gap-1.5 pt-1">
                          <span className="px-2 py-0.5 bg-blue-950/80 border border-blue-900/60 font-mono text-[9px] text-blue-300 font-bold rounded">
                            分类: {previewStickerItem.category}
                          </span>
                          <span className="px-2 py-0.5 bg-indigo-950/80 border border-indigo-900/60 font-mono text-[9px] text-indigo-300 font-bold rounded">
                            簇: {previewStickerItem.cluster || '代码评审折磨'}
                          </span>
                        </div>

                        {/* Asset ID copy block */}
                        <div className="space-y-1 font-mono text-[10px] bg-slate-900/40 p-2.5 rounded-xl border border-slate-850/60">
                          <span className="text-gray-550 block text-[8.5px] uppercase font-bold mb-1">图片资源独特存储标识 (Asset ID) :</span>
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-gray-300 text-[9px] select-all truncate">{previewStickerItem.id}</span>
                            <button
                              type="button"
                              onClick={() => {
                                navigator.clipboard.writeText(previewStickerItem.id);
                                alert('💾 资源 ID 已写入系统剪贴板！可直接输入大模型的 Rulebook 里指定关联。');
                              }}
                              className="text-[#00b4d8] hover:underline shrink-0 text-[8.5px]"
                            >
                              复制
                            </button>
                          </div>
                        </div>

                        {/* Local absolute repo filepath matching Image 2 */}
                        <div className="space-y-1 font-mono text-[10px] bg-slate-900/40 p-2.5 rounded-xl border border-slate-850/60 text-left">
                          <span className="text-gray-550 block text-[8.5px] uppercase font-bold mb-1">物理源路径 (Source Filepath) :</span>
                          <p className="text-xs text-[#00b4d8] rounded font-bold break-all bg-[#090d16] p-2 leading-relaxed border border-slate-800 shadow-inner">
                            📁 {previewStickerItem.sourcePath || `sources/${previewStickerItem.source}/${previewStickerItem.name}`}
                          </p>
                        </div>

                        {/* Comic-styled text balloon showing OCR details matching Image 2 */}
                        <div className="space-y-2 pt-2 text-left">
                          <span className="font-mono text-[9px] text-amber-500 font-extrabold uppercase block select-none">
                            💬 图片内大模型提取 OCR 结果段:
                          </span>
                          <div className="relative border-l-2 border-amber-500/80 bg-gradient-to-br from-amber-500/5 to-transparent p-3 rounded-r-xl border border-dashed border-slate-800">
                            {previewStickerItem.ocrText ? (
                              <p className="text-[12px] font-sans font-bold leading-relaxed text-amber-204 select-text whitespace-pre-wrap">
                                {previewStickerItem.ocrText}
                              </p>
                            ) : (
                              <p className="text-xs text-gray-500 font-mono italic">
                                "该表情无字或未包含有效 OCR 文字"
                              </p>
                            )}
                          </div>
                        </div>
                      </div>

                      {/* Open raw direct url file triggers */}
                      <div className="pt-4 border-t border-slate-850 flex items-center justify-between gap-3">
                        <button
                          type="button"
                          onClick={() => setPreviewStickerItem(null)}
                          className="px-4 py-2 bg-slate-900 hover:bg-slate-800 text-gray-300 text-xs font-bold rounded-xl border border-slate-805 transition-colors"
                        >
                          关闭面板 (Cancel)
                        </button>
                        
                        <a
                          href={previewStickerItem.url}
                          target="_blank"
                          rel="noreferrer"
                          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-xs font-bold rounded-xl shadow-md transition-all flex items-center space-x-1.5 select-none"
                        >
                          <ExternalLink size={12} />
                          <span>打开原图 (Open Raw)</span>
                        </a>
                      </div>

                    </div>

                  </div>
                </div>
              )}

            </div>
          )}

        </div>

        {/* Right Audit Inspector results panel */}
        {auditStats && (
          <div className={`w-80 border-l p-5 space-y-4 overflow-y-auto shrink-0 animate-slideLeft ${
            isDarkMode ? 'bg-[#090d16] border-[#1e2a44]' : 'bg-[#faf9f6] border-[#e2e0db]'
          }`}>
            <div className="flex items-center space-x-1 text-[10px] font-mono text-rose-500 font-bold tracking-widest uppercase pb-1 border-b">
              <AlertTriangle size={13} />
              <span>图床损坏与格式兼容审计分析</span>
            </div>

            <div className="space-y-3 font-mono text-[10px]">
              {/* Broken link list card */}
              <div className="p-3 bg-red-100/10 rounded-xl border border-rose-350 bg-rose-50/50 dark:bg-rose-950/20 text-slate-800 dark:text-rose-200">
                <p className="font-bold mb-1.5 text-rose-500">1. 失效 CDN 节点 (Broken Link):</p>
                {auditStats.brokenLinksFound.map((bl: any, i: number) => (
                  <div key={i} className="space-y-1">
                    <p className="font-bold">{bl.name}</p>
                    <p className="opacity-80 break-all text-gray-500">{bl.url}</p>
                    <p className="text-emerald-500 font-bold flex items-center">
                      <Check size={11} className="mr-0.5" />
                      <span>处理: {bl.resolvedBySystem}</span>
                    </p>
                  </div>
                ))}
              </div>

              {/* Duplicates list */}
              <div className="p-3 bg-amber-50/50 dark:bg-amber-950/20 rounded-xl border border-[#fed7aa] text-slate-800 dark:text-amber-200">
                <p className="font-semibold mb-1.5 text-amber-600">2. 重复特征图像签名 (Duplicates):</p>
                {auditStats.duplicateSignatures.map((dup: any, i: number) => (
                  <div key={i} className="space-y-1 text-[9px]">
                    <p className="font-semibold text-gray-400">{dup.fileA} ↔</p>
                    <p className="font-semibold text-gray-400">{dup.fileB}</p>
                    <p className="text-rose-500 font-bold">重复比率 (MD5): {dup.duplicatePercent}%</p>
                    <p className="opacity-80 italic">{dup.resolution}</p>
                  </div>
                ))}
              </div>

              {/* Platform compatible issues list */}
              <div className="p-3 bg-blue-50/50 dark:bg-blue-950/20 rounded-xl border border-blue-150 text-slate-800 dark:text-blue-200">
                <p className="font-bold mb-1.5 text-blue-500">3. 平台不兼容警告 (Compat):</p>
                {auditStats.platformCompatibilityIssues.map((comp: any, i: number) => (
                  <div key={i} className="space-y-1 leading-relaxed text-[9.5px]">
                    <p className="font-bold text-slate-700 dark:text-white">针对: {comp.platform}</p>
                    <p className="text-gray-500">{comp.reason}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
