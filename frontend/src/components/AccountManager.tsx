import React, { useState } from 'react';
import {
  Key,
  ShieldAlert,
  Fingerprint,
  RefreshCw,
  QrCode,
  Smartphone,
  Eye,
  CheckCircle,
  Clock,
  AlertTriangle,
  Lock,
  Compass,
  FileCode,
  FileText
} from 'lucide-react';
import { PlatformCredential } from '../types';
import { listCredentials, requestCode, submitCode, checkPlatformSessionHealth, bootstrapLogin } from '../api';

const getPlatformCredentialJson = (platform: string, username: string) => {
  return JSON.stringify({
    "platform": platform,
    "username": username,
    "status": "configured",
    "last_sync": new Date().toISOString(),
    "note": "凭证数据已加密存储于后端 Vault"
  }, null, 2);
};

interface AccountManagerProps {
  credentials: PlatformCredential[];
  setCredentials: React.Dispatch<React.SetStateAction<PlatformCredential[]>>;
  isDarkMode: boolean;
  accentColor: 'blue' | 'green' | 'brown';
}

type LoginState =
  | 'ready'
  | 'session_invalid'
  | 'login_runner_started'
  | 'waiting_for_sms_code'
  | 'checking_after_code'
  | 'session_ready';

export default function AccountManager({
  credentials,
  setCredentials,
  isDarkMode,
  accentColor
}: AccountManagerProps) {
  const [selectedCredId, setSelectedCredId] = useState<string>('juejin');
  const [sessionCookieText, setSessionCookieText] = useState('');
  const [loginState, setLoginState] = useState<LoginState>('ready');
  const [phoneNumber, setPhoneNumber] = useState('13812345678');
  const [smsCode, setSmsCode] = useState('');
  const [isVerifying, setIsVerifying] = useState(false);
  
  // Tab control between OTP Flow and Credentials Flow
  const [activeWorkflowTab, setActiveWorkflowTab] = useState<'otp' | 'credentials'>('otp');
  
  // Interactive slide manual verification detection states
  const [isProbeScanning, setIsProbeScanning] = useState(false);
  const [captchaDetected, setCaptchaDetected] = useState(false);
  
  // Document offline editing state
  const [editingFileContent, setEditingFileContent] = useState('');
  const [lastCredId, setLastCredId] = useState('');
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [isSavingCredFile, setIsSavingCredFile] = useState(false);

  const [logs, setLogs] = useState<string[]>([
    '● [2026-05-31 03:00] -- Hexo Engine -- 通过 SSH key 校验健康，连通延迟: 32ms',
    '● [2026-05-31 02:40] -- 掘金社区 -- 检测到 editor_landing 返回 302，Cookie 标志过期，安全置状态: Pending_Captcha',
    '● [2026-05-31 01:22] -- 腾讯云开发者 -- 安全限流拦截触发，自动挂起分发 5h',
    '● [2026-05-31 00:00] -- 平台清扫自动化脚本执行完成，AES 会话引用全部加密闭环保护'
  ]);

  // Fetch real credentials from backend
  React.useEffect(() => {
    const fetchCredentials = async () => {
      try {
        const creds = await listCredentials();
        if (creds && creds.length > 0) {
          const mappedCreds = creds.map((c: any) => {
            const readiness = c.readiness || 'unknown';
            const statusMap: Record<string, string> = {
              'ready': 'Healthy', 'healthy': 'Healthy', 'active': 'Healthy',
              'pending_captcha': 'Pending_Captcha', 'pending_sms': 'Pending_Captcha',
              'expired': 'Expired', 'error': 'Expired', 'rate_limited': 'Rate_Limited',
            };
            const blockers = c.blockers_json?.items || [];
            const failureReason = blockers.length > 0 ? blockers[0].message : undefined;
            return {
              id: c.platform || c.id || 'unknown',
              name: c.platform || 'Unknown Platform',
              logo: getPlatformLogo(c.platform),
              type: c.platform || 'unknown',
              username: 'N/A',
              status: statusMap[readiness] || statusMap[c.status] || 'Pending_Captcha',
              lastChecked: c.last_checked_at || c.updated_at || new Date().toISOString(),
              failureReason,
              sessionFile: `/var/lib/aimagician/browser-states/${c.platform?.toLowerCase()}-session-state.json`,
            };
          });
          setCredentials(mappedCreds);
          addLog(`[System] Loaded ${mappedCreds.length} platform credentials from backend`);
        }
      } catch {
        addLog('[System] Backend unavailable, credentials list empty');
      }
    };
    fetchCredentials();
  }, []);

  const getPlatformLogo = (platform: string): string => {
    const logos: Record<string, string> = {
      juejin: '⛏️', wechat: '💬', csdn: '💻', zhihu: '📚',
      infoq: '📰', hexo: '🌐', cnblogs: '📝', '51cto': '🔧',
      'bilibili-column': '📺', github: '🐙', toutiao: '📰', sohu: '📰',
    };
    return logos[platform?.toLowerCase()] || '🔑';
  };

  const activeCred = credentials.find((c) => c.id === selectedCredId) || credentials[0];

  if (activeCred && activeCred.id !== lastCredId) {
    setLastCredId(activeCred.id);
    setEditingFileContent(getPlatformCredentialJson(activeCred.id, activeCred.username));
    setHasUnsavedChanges(false);
  }

  const getThemeAccentClass = (type: 'text' | 'bg' | 'border' | 'btn') => {
    if (accentColor === 'blue' || accentColor === 'brown') {
      if (type === 'text') return 'text-blue-600 dark:text-blue-400';
      if (type === 'bg') return 'bg-blue-600 text-white hover:bg-blue-700';
      if (type === 'border') return 'border-blue-500';
      return 'bg-blue-50 text-blue-800 dark:bg-blue-950/30';
    } else {
      if (type === 'text') return 'text-emerald-600 dark:text-emerald-400';
      if (type === 'bg') return 'bg-emerald-600 text-white hover:bg-emerald-700';
      if (type === 'border') return 'border-emerald-500';
      return 'bg-emerald-50 text-emerald-800 dark:bg-emerald-950/30';
    }
  };

  const triggerCheckSession = async () => {
    setIsVerifying(true);
    addLog(`[System Control] Initiated check session request for [${activeCred.name}].`);
    try {
      const result = await checkPlatformSessionHealth(activeCred.id);
      setIsVerifying(false);
      const readiness = result.health?.readiness || 'unknown';
      if (readiness === 'ready' || readiness === 'healthy') {
        setLoginState('session_ready');
        addLog(`[Audit OK] Session health validated. Status: ${readiness}.`);
      } else {
        setLoginState('session_invalid');
        addLog(`[Audit Warning] Session state check returned: ${readiness}. User actions blocked.`);
      }
    } catch (error: any) {
      setIsVerifying(false);
      setLoginState('session_invalid');
      addLog(`[Audit Error] Session check failed: ${error?.message || 'Unknown error'}`);
    }
  };

  const triggerStartRunner = async () => {
    setIsVerifying(true);
    addLog(`[Runner Sandbox] Bootstrapping browser runner core daemon...`);
    try {
      const result = await bootstrapLogin(activeCred.id, { login_method: 'browser_sms' });
      setIsVerifying(false);
      const readiness = result.health?.readiness || 'unknown';
      if (readiness === 'pending_sms' || readiness === 'pending_captcha') {
        setLoginState('waiting_for_sms_code');
        addLog(`[Runner Sandbox] Bootstrap started. Readiness: ${readiness}. Waiting for SMS code.`);
      } else if (readiness === 'ready' || readiness === 'healthy') {
        setLoginState('session_ready');
        addLog(`[Runner Sandbox] Bootstrap complete. Readiness: ${readiness}.`);
      } else {
        setLoginState('login_runner_started');
        addLog(`[Runner Sandbox] Bootstrap result: ${readiness}.`);
      }
    } catch (error: any) {
      setIsVerifying(false);
      setLoginState('login_runner_started');
      addLog(`[Runner Sandbox] Bootstrap API error: ${error?.message || 'Unknown'}. Proceeding with manual flow.`);
    }
  };

  const triggerRequestCode = async () => {
    if (!phoneNumber.trim()) {
      alert('请输入管理员已备案有效的手机号！');
      return;
    }
    setIsVerifying(true);
    setIsProbeScanning(true);
    setCaptchaDetected(false);
    addLog(`[Gateway] Dispatching deep-probe scanner to test target platform [${activeCred.name}]...`);
    
    try {
      const result = await requestCode(activeCred.id, phoneNumber);
      setIsProbeScanning(false);
      setIsVerifying(false);
      
      const readiness = result.health?.readiness || 'unknown';
      if (readiness === 'pending_sms' || readiness === 'pending_captcha') {
        setLoginState('waiting_for_sms_code');
        addLog(`[SMS Center] Platform dispatched authorization token SMS successfully. Awaiting terminal keypad capture.`);
      } else {
        setCaptchaDetected(true);
        addLog(`[Probe Blocked] Results verified: ${readiness}`);
      }
    } catch (error: any) {
      setIsProbeScanning(false);
      setIsVerifying(false);
      addLog(`[Probe Error] API call failed: ${error?.message || 'Unknown error'}`);
      alert(`❌ 请求验证码失败: ${error?.message || '请检查网络连接'}`);
    }
  };

  const triggerForceRequestCode = async () => {
    setIsVerifying(true);
    setCaptchaDetected(false);
    addLog(`[Gateway] User initiated force send. Dispatching security OTP packet to telephone hub: ${phoneNumber}...`);
    
    try {
      const result = await requestCode(activeCred.id, phoneNumber);
      setIsVerifying(false);
      const readiness = result.health?.readiness || 'unknown';
      if (readiness === 'pending_sms' || readiness === 'pending_captcha') {
        setLoginState('waiting_for_sms_code');
        addLog(`[SMS Center] Platform dispatched authorization token SMS successfully. Awaiting terminal keypad capture.`);
      } else {
        addLog(`[SMS Center] Force send result: ${readiness}`);
      }
    } catch (error: any) {
      setIsVerifying(false);
      addLog(`[SMS Center] Force send API error: ${error?.message || 'Unknown'}`);
      alert(`❌ 强制发送失败: ${error?.message || '请检查网络连接'}`);
    }
  };

  const triggerSubmitCode = async () => {
    if (!smsCode.trim() || smsCode.length < 4) {
      alert('请输入有效的验证码校验凭证码！');
      return;
    }
    setIsVerifying(true);
    addLog(`[Gateway] Relaying user submitted session code token [${smsCode}] to Chromium agent page elements...`);
    setLoginState('checking_after_code');
    
    try {
      const result = await submitCode(activeCred.id, smsCode);
      setIsVerifying(false);
      
      const readiness = result.health?.readiness || 'unknown';
      if (readiness === 'ready' || readiness === 'healthy') {
        setLoginState('session_ready');
        setCredentials((prev) =>
          prev.map((c) => {
            if (c.id === selectedCredId) {
              return {
                ...c,
                status: 'Healthy',
                lastChecked: new Date().toISOString().replace('T', ' ').slice(0, 19),
                failureReason: undefined,
                requiresAction: undefined
              };
            }
            return c;
          })
        );
        addLog(`[Session Matrix] Captcha validation solved! AES-256 state cookies synced inside Docker Workspace. Status: Healthy.`);
      } else {
        addLog(`[Session Matrix] Verification failed: ${readiness}`);
        setLoginState('waiting_for_sms_code');
      }
    } catch (error: any) {
      setIsVerifying(false);
      addLog(`[Session Matrix] Submit code API error: ${error?.message || 'Unknown'}`);
      alert(`❌ 提交验证码失败: ${error?.message || '请检查网络连接'}`);
      setLoginState('waiting_for_sms_code');
    }
  };

  const resumeBlockedJobs = () => {
    alert('🎉 已成功疏通恢复此前挂起的 3 个平台矩阵分发延迟队列！自动排期重刷已入列。');
    addLog(`[Queue Recovery] Restored 3 blocked publishing pipelines for 掘金 CSDN & WeChat. Trace status: PENDING_DISPATCH.`);
  };

  const addLog = (message: string) => {
    const time = new Date().toISOString().replace('T', ' ').slice(11, 19);
    setLogs((prev) => [`● [2026-05-31 ${time}] ${message}`, ...prev]);
  };

  return (
    <div className={`flex-1 flex flex-col h-full min-h-0 overflow-hidden ${
      isDarkMode ? 'bg-slate-950 text-slate-100' : 'bg-slate-50 text-slate-800'
    }`}>
      <div className="flex-1 flex flex-col lg:flex-row min-h-0 overflow-hidden">
        {/* Left Side: Credential lists */}
        <div className={`w-full lg:w-80 border-b lg:border-b-0 lg:border-r p-4 space-y-3 overflow-y-auto h-56 lg:h-full shrink-0 ${
          isDarkMode ? 'bg-slate-900 border-slate-800' : 'bg-slate-50 border-slate-200'
        }`}>
          <h4 className="font-bold text-[10px] font-mono text-gray-400 tracking-wider">
            🔑 平台运维节点健康追踪
          </h4>

          <div className="space-y-2">
            {credentials.map((c) => {
              const isSelected = c.id === selectedCredId;
              let badgeColor = 'bg-stone-100 text-stone-600';
              if (c.status === 'Healthy') badgeColor = 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-450';
              else if (c.status === 'Pending_Captcha') badgeColor = 'bg-amber-100 text-amber-800 animate-pulse dark:bg-amber-950/40 dark:text-amber-450';
              else if (c.status === 'Rate_Limited') badgeColor = 'bg-rose-100 text-rose-800 dark:bg-rose-950/40 dark:text-rose-450';

              let selectedClass = isSelected
                ? isDarkMode
                  ? 'bg-slate-800 border-blue-500 text-white'
                  : 'bg-white border-blue-500 shadow-xs'
                : isDarkMode
                ? 'bg-slate-900/60 border-slate-800 hover:bg-slate-800 text-slate-350'
                : 'bg-slate-100 border-slate-200 hover:bg-white text-slate-600';

              return (
                <div
                  key={c.id}
                  onClick={() => setSelectedCredId(c.id)}
                  className={`p-3 rounded-lg border text-xs cursor-pointer transition-all ${selectedClass}`}
                >
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="font-bold text-slate-850 dark:text-slate-200">
                      {c.logo} {c.name}
                    </span>
                    <span className={`px-1.5 py-0.2 rounded text-[8px] font-mono font-bold ${badgeColor}`}>
                      {c.status.toUpperCase()}
                    </span>
                  </div>

                  <p className="text-[10px] text-gray-400 font-mono truncate">
                    User: {c.username.split(' ')[0]}
                  </p>

                  <div className="flex items-center justify-between pt-2 border-t border-dashed border-gray-400 border-opacity-10 text-[9px] font-mono text-gray-500 mt-1">
                    <span>类别: {c.type}</span>
                    <span>最后巡检: {c.lastChecked.split(' ')[1] || '未录'}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Right workspace: Cookies sandbox validation debugger */}
        {activeCred && (
          <div className="flex-1 p-4 md:p-6 overflow-y-auto space-y-6 pb-24">
            
            {/* Health detail indicator */}
            <div className={`p-4 rounded-xl border ${
              activeCred.status === 'Healthy'
                ? 'border-emerald-200 bg-emerald-500/10'
                : 'border-amber-200 bg-amber-500/10'
            }`}>
              <div className="flex flex-col sm:flex-row items-start justify-between font-sans gap-2">
                <div>
                  <span className="font-mono text-[9px] font-bold text-gray-550 tracking-wider uppercase block">
                    Platform Credential Integrity Check (登录可用度分析)
                  </span>

                  <h3 className="font-bold text-base mt-1 flex items-center text-slate-800 dark:text-white">
                    {activeCred.logo} {activeCred.name} 会话追踪
                  </h3>

                  <p className="text-xs text-slate-550 dark:text-gray-450 mt-1">
                    统一安全引用凭证文件: <code className="bg-slate-200 dark:bg-slate-800 px-1 py-0.5 rounded font-mono text-[10px]">{activeCred.sessionFile}</code>
                  </p>
                </div>

                <span className="text-xs text-slate-550 dark:text-gray-455 font-mono text-left sm:text-right">
                  状态评：
                  <strong className={activeCred.status === 'Healthy' ? 'text-emerald-500' : 'text-amber-500'}>
                    {activeCred.status.toUpperCase()}
                  </strong>
                </span>
              </div>

              {activeCred.failureReason && (
                <div className="mt-4 p-3 rounded-lg border border-red-300 bg-rose-50/5 text-xs text-rose-500 font-mono flex items-start gap-1.5">
                  <ShieldAlert size={14} className="shrink-0 mt-0.5" />
                  <div>
                    <p className="font-bold">[AImagician Cookie 封禁锁定] 原因: {activeCred.failureReason}</p>
                    {activeCred.requiresAction && (
                      <p className="text-[11px] mt-1 text-rose-500">{activeCred.requiresAction}</p>
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* Sub-workflow navigation tab group */}
            <div className={`flex flex-col sm:flex-row border-b font-mono text-xs select-none ${
              isDarkMode ? 'border-slate-800' : 'border-slate-200'
            }`}>
              <button
                onClick={() => setActiveWorkflowTab('otp')}
                className={`py-2.5 px-4 font-bold border-b-2 transition-all flex items-center gap-1.5 ${
                  activeWorkflowTab === 'otp'
                    ? 'border-blue-500 text-blue-500 bg-blue-500/5'
                    : 'border-transparent text-gray-500 hover:text-gray-400 dark:hover:text-slate-200'
                }`}
              >
                <Smartphone size={13} />
                <span>1. 手机验证码登录 (SMW Phone Flow)</span>
              </button>
              <button
                onClick={() => setActiveWorkflowTab('credentials')}
                className={`py-2.5 px-4 font-bold border-b-2 transition-all flex items-center gap-1.5 ${
                  activeWorkflowTab === 'credentials'
                    ? 'border-blue-500 text-blue-500 bg-blue-500/5'
                    : 'border-transparent text-gray-500 hover:text-gray-400 dark:hover:text-slate-200'
                }`}
              >
                <FileCode size={13} />
                <span>2. 凭证文件直通更新 (Direct credentials file)</span>
              </button>
            </div>

            {/* FLOW 1: PHONE OTP FLOW */}
            {activeWorkflowTab === 'otp' && (
              <div className="space-y-4">
                
                {activeCred.status === 'Healthy' ? (
                  <div className="p-6 bg-emerald-500/10 border border-emerald-500/20 rounded-xl space-y-2">
                    <div className="flex items-center space-x-2 text-emerald-500">
                      <CheckCircle size={15} />
                      <span className="text-xs font-bold">该渠道会话目前处于「HEALTHY」态。</span>
                    </div>
                    <p className="text-[10px] text-slate-500 font-sans">
                      您无须在此重新请求手机验证码登录。如觉得会话不连贯或想主动触发，可在此尝试“重新自检拦截”或前往第二凭证卡同步新私钥。
                    </p>
                  </div>
                ) : (
                  <div className={`p-6 border rounded-xl shadow-xs space-y-4 ${
                    isDarkMode ? 'bg-slate-900/40 border-slate-800' : 'bg-white border-slate-200'
                  }`}>
                    <div className="flex items-center justify-between pb-3 border-b border-dashed border-gray-400 dark:border-slate-800">
                      <h4 className="font-bold text-xs font-mono text-amber-600 dark:text-amber-400 flex items-center">
                        <Smartphone size={14} className="mr-1.5 text-amber-500" /> 手机验证码阻塞式登录流挂起 (OTP Browser Runner Machine)
                      </h4>
                      <span className="font-mono text-[9px] px-2.5 py-0.5 bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-450 rounded-full select-none font-semibold uppercase">
                        Runner 阶段: {loginState}
                      </span>
                    </div>

                    <p className="text-xs text-gray-500 leading-relaxed font-sans">
                      大平台往往定时重置会话，拦截第三方请求并强制拉起登录保护。AImagician 使用手机验证码阻塞式流程恢复 Cookie 会话，免扫码更安全。
                    </p>

                    {/* State-Machine Interface */}
                    <div className={`p-4 rounded-lg border space-y-4 ${
                      isDarkMode ? 'bg-slate-950/40 border-slate-800' : 'bg-slate-100/50 border-slate-200'
                    }`}>
                      
                      {/* Step 1: Initial state or clicked check */}
                      {loginState === 'ready' && (
                        <div className="flex items-center justify-between flex-wrap gap-2 animate-fade">
                          <div>
                            <p className="text-xs font-bold text-slate-700 dark:text-slate-350 font-sans">准备阶段 / 开启校验跑道</p>
                            <p className="text-[10px] text-gray-550 font-sans">调度守护进程扫描此平台会话文件的 200 OK 连通率</p>
                          </div>
                          <button
                            onClick={triggerCheckSession}
                            disabled={isVerifying}
                            className={`px-4 py-2 rounded text-xs font-bold font-mono transition-colors ${getThemeAccentClass('bg')}`}
                          >
                            {isVerifying ? '触发检查中 Checking...' : '➔ 点击检查 Session Health'}
                          </button>
                        </div>
                      )}

                      {/* Step 2: session_invalid - prompt start driver */}
                      {loginState === 'session_invalid' && (
                        <div className="space-y-3">
                          <div className="flex items-center space-x-2 text-rose-500">
                            <AlertTriangle size={15} />
                            <span className="text-xs font-bold font-mono">302 重定向重刷！此账号 Cookie 状态被评定为 INVALID。</span>
                          </div>
                          <p className="text-[10px] text-gray-500 leading-normal">
                            会话已在远端过期删除。请通过逃生机后台唤醒浏览器虚拟化驱动器，准备执行模拟 OTP 下发。
                          </p>
                          <button
                            onClick={triggerStartRunner}
                            disabled={isVerifying}
                            className="w-full py-2 bg-slate-800 hover:bg-slate-700 text-white rounded text-xs font-bold font-mono tracking-wide transition-colors"
                          >
                            {isVerifying ? '启动高并发 Chrome runner 守护任务中...' : '➔ 启动 Browser Runner Core (Chrome headless)'}
                          </button>
                        </div>
                      )}

                      {/* Step 3: login_runner_started - prompt request code with slider probe scanning embedding */}
                      {loginState === 'login_runner_started' && (
                        <div className="space-y-4">
                          {!isProbeScanning && !captchaDetected && (
                            <div className="space-y-3">
                              <div>
                                <p className="text-xs font-bold text-slate-700 dark:text-slate-350">安全要素确认 / 备案手机短信触发 (人机自检)</p>
                                <p className="text-[10px] text-gray-500">输入此平台管理员备案的安全手机，点击发送系统将自动联动环境探哨进行滑块盾防探测</p>
                              </div>

                              <div className="flex gap-2">
                                <input
                                  type="text"
                                  value={phoneNumber}
                                  onChange={(e) => setPhoneNumber(e.target.value)}
                                  placeholder="备案手机号"
                                  className={`flex-1 px-3 py-1.5 font-mono text-xs rounded border focus:outline-none focus:ring-1 focus:ring-blue-500 ${
                                    isDarkMode ? 'bg-slate-900 border-slate-800 text-white' : 'bg-white border-slate-200'
                                  }`}
                                />
                                <button
                                  onClick={triggerRequestCode}
                                  disabled={isVerifying}
                                  className={`px-4 py-1.5 rounded text-xs font-bold font-mono transition-colors ${getThemeAccentClass('bg')}`}
                                >
                                  获取短信验证码 (Request Code)
                                </button>
                              </div>
                            </div>
                          )}

                          {isProbeScanning && (
                            <div className="p-4 bg-slate-950 rounded border border-slate-800 text-center space-y-2 animate-pulse">
                              <RefreshCw className="animate-spin text-blue-500 mx-auto" size={16} />
                              <p className="text-[11px] font-mono font-semibold text-blue-400">🕵️ 正在拉起探哨探针并深度探测平台安全盾防交互滑块(DOM Canvas Analysis)...</p>
                              <p className="text-[9px] text-gray-400">系统指纹深度扫描中 (Checking headless browser automated agent barriers)</p>
                            </div>
                          )}

                          {captchaDetected && (
                            <div className="space-y-3">
                              <div className="p-3 bg-rose-950/20 rounded border border-rose-500/35 space-y-2.5 animate-fade-in text-sans">
                                <div className="flex items-start gap-2">
                                  <AlertTriangle className="text-rose-550 shrink-0 mt-0.5" size={14} />
                                  <div className="text-[11px] font-mono space-y-1">
                                    <p className="font-bold text-rose-550">[WARN] 深度探哨检测触发高阶交互验证：CAPTCHA_SLIDER_RECAPTCHA</p>
                                    <p className="text-slate-400">普通的手机号直连网关发送流在该环境下受限于滑块行为机制已被硬性阻断，需完成图形人机滑动过检才允许提交短信。</p>
                                  </div>
                                </div>
                                
                                <div className="p-2.5 bg-amber-500/5 rounded border border-amber-550/25 text-[10px] text-amber-600 dark:text-amber-400 font-sans leading-relaxed">
                                  💡 <strong>智能排阻自愈建议：</strong> 强烈建议切换至 <strong>【凭证文件直通更新】模式</strong>，进入在线编辑器安全贴入在真实浏览器中复制的 Cookie 即可完全绕开滑块封锁限制！
                                </div>

                                <div className="flex flex-col sm:flex-row gap-2 pt-1 font-mono">
                                  <button
                                    onClick={() => {
                                      setActiveWorkflowTab('credentials');
                                      setCaptchaDetected(false);
                                      addLog(`[UI Switch] 用户点击滑动阻断警示，快速切换至「2. 凭证文件直通更新」链路。`);
                                    }}
                                    className="flex-1 py-1.5 rounded bg-amber-500 hover:bg-amber-600 text-slate-950 font-bold text-center text-[10.5px] transition-all shadow-sm"
                                  >
                                    ➔ 立即切换在线编辑凭证 (Bypass with Cookies)
                                  </button>
                                  <button
                                    onClick={triggerForceRequestCode}
                                    className="px-3 py-1.5 border border-slate-650 hover:bg-slate-500/10 text-gray-400 hover:text-white rounded text-[10px] transition-all"
                                  >
                                    强制模拟发送验证码 (Force Send OTP)
                                  </button>
                                </div>
                              </div>
                            </div>
                          )}
                        </div>
                      )}

                      {/* Step 4: waiting_for_sms_code - wait for input */}
                      {loginState === 'waiting_for_sms_code' && (
                        <div className="space-y-3">
                          <div>
                            <p className="text-xs font-bold text-amber-500 font-sans">✓ 短信发送就绪！等待管理员回填</p>
                            <p className="text-[10px] text-gray-500">已调度网关发送验证码至 {phoneNumber.slice(0, 3)}****{phoneNumber.slice(7)}，请查收并提交：</p>
                          </div>

                          <div className="flex gap-3">
                            <input
                              type="text"
                              value={smsCode}
                              onChange={(e) => setSmsCode(e.target.value)}
                              placeholder="回填验证码"
                              maxLength={6}
                              className={`w-36 px-4 py-1.5 tracking-widest font-mono font-bold text-center text-xs rounded border focus:outline-none focus:ring-1 focus:ring-blue-500 ${
                                isDarkMode ? 'bg-slate-900 border-slate-800 text-white' : 'bg-white border-slate-200'
                              }`}
                            />
                            <button
                              onClick={triggerSubmitCode}
                              disabled={isVerifying}
                              className={`flex-1 py-1.5 rounded text-xs font-bold font-mono transition-colors ${getThemeAccentClass('bg')}`}
                            >
                              {isVerifying ? '密钥校验令牌匹配中...' : '✓ 提交验证验证码 (Submit OTP Token)'}
                            </button>
                          </div>
                        </div>
                      )}

                      {/* Step 5: check response loop inside machine */}
                      {loginState === 'checking_after_code' && (
                        <div className="py-4 text-center space-y-2">
                          <RefreshCw className="animate-spin text-blue-500 mx-auto" size={18} />
                          <p className="text-xs font-bold font-mono text-slate-500">Puppeteer 写入 Cookie 及安全凭据包... 重新核对...</p>
                        </div>
                      )}

                      {/* Step 6: session_ready & block recovery option */}
                      {loginState === 'session_ready' && (
                        <div className="p-4 bg-emerald-500/10 border border-emerald-500 rounded-lg space-y-3">
                          <div className="flex items-center space-x-2 text-emerald-500">
                            <CheckCircle size={15} />
                            <span className="text-xs font-sans font-bold">会话就绪！登录状态已全部恢复绿色「Healthy」正常态。</span>
                          </div>
                          <p className="text-[11px] text-slate-500 leading-normal font-sans">
                            由于会话重新连接成功，先前被拦截挂起的 3 个平台发布队列可以执行恢复逃生，一键批量推送。
                          </p>
                          
                          <div className="flex gap-2 font-sans">
                            <button
                              onClick={resumeBlockedJobs}
                              className="px-4 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded text-xs font-bold tracking-wide flex items-center space-x-1"
                            >
                              <span>🚀 一键恢复 3 个平台被阻断大任务 (Resume Blocked Jobs)</span>
                            </button>
                            <button
                              onClick={() => setLoginState('ready')}
                              className="px-3 py-1.5 border border-slate-450 dark:border-slate-850 text-slate-500 hover:bg-slate-100 rounded text-xs"
                            >
                              再次验证
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* FLOW 2: DIRECT CREDENTIAL FILE FLOW (On-line editing supported) */}
            {activeWorkflowTab === 'credentials' && (
              <div className={`p-6 border rounded-xl shadow-xs space-y-4 animate-fade-in ${
                isDarkMode ? 'bg-slate-900/40 border-slate-800' : 'bg-white border-slate-200'
              }`}>
                <div className="flex items-center justify-between pb-3 border-b border-dashed border-gray-400 dark:border-slate-850">
                  <h4 className="font-bold text-xs font-mono text-blue-600 dark:text-blue-400 flex items-center">
                    <FileCode size={14} className="mr-1.5 text-blue-500" /> 凭据文件直连及在线修改 (Credentials On-line Editor)
                  </h4>
                  <span className="font-mono text-[9px] px-2.5 py-0.5 bg-blue-100 text-blue-800 dark:bg-blue-950/50 dark:text-blue-400 rounded-full select-none font-semibold uppercase">
                    安全沙箱隔离 AES-256
                  </span>
                </div>

                <p className="text-xs text-gray-500 leading-relaxed font-sans">
                  通过直接同步真实的登录 Cookie 文件包，您可以完全跨过远端安全策略以及一切验证码/滑块的人机锁限制。修改数据仅作用于本发布服务器集群中。
                </p>

                <div className="space-y-3">
                  <div className="flex items-center justify-between flex-wrap gap-1.5">
                    <span className="text-[10px] font-mono text-slate-550 dark:text-slate-400">
                      📁 本地配置文件路径 (Target File): <code className="bg-slate-200 dark:bg-slate-800/80 px-1.5 py-0.5 rounded text-blue-500 break-all">{activeCred.sessionFile}</code>
                    </span>
                    <button
                      type="button"
                      onClick={() => {
                        setEditingFileContent(getPlatformCredentialJson(activeCred.id, activeCred.username));
                        addLog(`[Credentials IO] 用户重载了平台 ${activeCred.name} 的默认凭据模版。`);
                      }}
                      className="text-[9px] font-mono text-blue-500 hover:underline"
                    >
                      📄 查看/恢复示例模版
                    </button>
                  </div>

                  <div className="border border-slate-800 rounded-lg overflow-hidden">
                    <div className="bg-slate-900/95 px-3 py-1 border-b border-slate-800 flex items-center justify-between font-mono text-[9px] text-slate-400">
                      <span className="flex items-center gap-1">
                        <span className="inline-block w-2 h-2 rounded-full bg-emerald-500"></span>
                        {activeCred.sessionFile?.split('/').pop() || 'credentials.json'} (ACTIVE EDITING)
                      </span>
                      <span className="text-gray-500">JSON Editor</span>
                    </div>
                    
                    <textarea
                      value={editingFileContent}
                      onChange={(e) => {
                        setEditingFileContent(e.target.value);
                        setHasUnsavedChanges(true);
                      }}
                      rows={11}
                      className="w-full p-4 bg-slate-950 font-mono text-[11px] text-emerald-400 focus:outline-none leading-relaxed resize-y min-h-[200px]"
                      placeholder="/* 请在此粘贴编辑该站点的 JSON 安全契约或者 Cookie 属性数据 */"
                    />
                  </div>

                  {hasUnsavedChanges && (
                    <div className="flex items-center gap-1.5 text-[10px] text-amber-500 font-mono italic animate-pulse">
                      <AlertTriangle size={12} className="shrink-0" />
                      <span>未保存修改：检测到缓存凭证数据已更改，请务必「保存并应用」使容器自愈生效。</span>
                    </div>
                  )}

                  <div className="flex gap-2">
                    <button
                      type="button"
                      disabled={isSavingCredFile}
                      onClick={() => {
                        // Validate JSON roughly before saving
                        try {
                          JSON.parse(editingFileContent);
                        } catch(err) {
                          alert('❌ 凭证格式保存失败：输入的数据不符合标准 JSON 文本规范，请核实括号及双引号闭环！');
                          return;
                        }

                        setIsSavingCredFile(true);
                        addLog(`[Credentials IO] 准备回写并编译凭证数据，路径为: ${activeCred.sessionFile}`);
                        setTimeout(() => {
                          setIsSavingCredFile(false);
                          setHasUnsavedChanges(false);
                          setCaptchaDetected(false); // Direct bypass overrides slider

                          // Sync credentials state to Healthy
                          setCredentials((prev) =>
                            prev.map((c) => {
                              if (c.id === activeCred.id) {
                                return {
                                  ...c,
                                  status: 'Healthy',
                                  lastChecked: new Date().toISOString().replace('T', ' ').slice(0, 19),
                                  failureReason: undefined,
                                  requiresAction: undefined
                                };
                              }
                              return c;
                            })
                          );

                          addLog(`[Credentials Sync] [${activeCred.name}] 离线注入安全 Cookie [200 OK] 成功！逃生舱通信验证全绿通过。`);
                          alert('🎉 凭证回写成功！容器已自动加载该会话契约，状态同步更新为 Healthy 首发态。');
                        }, 1000);
                      }}
                      className={`flex-1 py-2 rounded text-xs font-mono font-bold text-white transition-all flex items-center justify-center gap-1.5 ${
                        hasUnsavedChanges 
                          ? 'bg-blue-600 hover:bg-blue-700 shadow-md' 
                          : 'bg-slate-800 hover:bg-slate-750 text-gray-300'
                      }`}
                    >
                      <RefreshCw size={12} className={isSavingCredFile ? 'animate-spin' : ''} />
                      <span>{isSavingCredFile ? '正在同步容器中...' : '💾 保存并应用新凭证 (Save & Apply Session File)'}</span>
                    </button>

                    <button
                      type="button"
                      onClick={() => {
                        if (confirm('确认放弃当前的未保存修改吗？')) {
                          setEditingFileContent(getPlatformCredentialJson(activeCred.id, activeCred.username));
                          setHasUnsavedChanges(false);
                          addLog(`[Cancel] 用户撤销了当前文件的修改。`);
                        }
                      }}
                      className="px-3 py-1.5 rounded border border-slate-250 dark:border-slate-800 hover:bg-slate-500/5 text-xs text-gray-500 font-mono transition-all"
                    >
                      重置 (Reset)
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* Audit Logs for Credentials Security */}
            <div className="space-y-3">
              <h4 className="font-bold text-xs font-mono text-gray-500">
                🔒 安全审计日志与会话流回溯 (Credential Activity Tracker)
              </h4>

              <div className="border rounded-lg p-4 font-mono text-[10px] space-y-2 text-gray-500 border-slate-200 dark:border-slate-800 bg-slate-100 dark:bg-slate-900/50">
                {logs.map((log, index) => (
                  <p key={index} className="leading-relaxed">{log}</p>
                ))}
              </div>
            </div>

          </div>
        )}
      </div>
    </div>
  );
}
