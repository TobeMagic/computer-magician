import React, { useState } from 'react';
import { Key, Mail, ShieldAlert, ArrowRight, Cpu, Sun, Moon, CheckCircle2, Feather, Eye, EyeOff } from 'lucide-react';
import { login, ApiError } from '../api';

interface LoginScreenProps {
  onLoginSuccess: (email: string) => void;
  isDarkMode: boolean;
  setIsDarkMode: (val: boolean) => void;
  accentColor: 'blue' | 'green' | 'brown';
}

export default function LoginScreen({
  onLoginSuccess,
  isDarkMode,
  setIsDarkMode,
  accentColor
}: LoginScreenProps) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadingStep, setLoadingStep] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!email.trim()) {
      setError('请输入登录管理员账户 (Email)');
      return;
    }
    if (!password) {
      setError('请输入专属安全授权密码');
      return;
    }

    setLoading(true);
    setLoadingStep(1);

    try {
      setLoadingStep(2);
      await login(email, password);
      setLoadingStep(3);
      onLoginSuccess(email);
    } catch (err) {
      setLoading(false);
      setLoadingStep(0);
      if (err instanceof ApiError) {
        if (err.status === 401) {
          setError('账户或密码错误，请检查后重试');
        } else {
          setError(`登录失败: ${err.message}`);
        }
      } else {
        setError('网络连接失败，请检查后端服务是否运行');
      }
    }
  };

  const loadingSteps = [
    '',
    '正在校验个人凭证结构...',
    '激活中枢控制面板...',
    '进入 AImagician 创作空间...'
  ];

  // Stateful image sources with multi-tier automatic fallbacks for maximum reliability
  const [starryImg, setStarryImg] = useState("/starry_night.jpg");
  const [wheatImg, setWheatImg] = useState("/wheat_field.jpg");

  return (
    <div id="immersive_login_portal" className={`fixed inset-0 w-screen h-screen z-50 overflow-hidden flex flex-col md:flex-row justify-center md:justify-end items-center font-sans select-none transition-colors duration-1000 ${
      isDarkMode ? 'bg-[#030616]' : 'bg-[#e2f1f6]'
    }`}>
      
      {/* =========================================================================
          BACKGROUND ARTWORK: AUTHENTIC HIGH-RES VAN GOGH DIGITAL MASTERPIECES
          ========================================================================= */}
      <div className="absolute inset-0 pointer-events-none z-0 overflow-hidden">
        
        {/* Starry Night (Dark Mode background image) */}
        <img 
          src={starryImg}
          alt="Van Gogh - Starry Night"
          referrerPolicy="no-referrer"
          onError={() => {
            // Alternative mirror for Starry Night
            setStarryImg("https://upload.wikimedia.org/wikipedia/commons/thumb/e/ea/Van_Gogh_-_Starry_Night_-_Google_Art_Project.jpg/1280px-Van_Gogh_-_Starry_Night_-_Google_Art_Project.jpg");
          }}
          className={`absolute inset-0 w-full h-full object-cover transition-opacity duration-1000 ease-in-out scale-[1.02] ${
            isDarkMode ? 'opacity-100' : 'opacity-0'
          }`}
          style={{
            objectPosition: '50% 60%'
          }}
        />

        {/* Wheat Field with Cypresses (Light Mode background image) */}
        <img 
          src={wheatImg}
          alt="Van Gogh - Wheat Field with Cypresses"
          referrerPolicy="no-referrer"
          onError={() => {
            // Alternative mirror for Wheat Field
            setWheatImg("https://upload.wikimedia.org/wikipedia/commons/thumb/c/ce/Wheat-Field-with-Cypresses-%281889%29-Vincent-van-Gogh-Met.jpg/1280px-Wheat-Field-with-Cypresses-%281889%29-Vincent-van-Gogh-Met.jpg");
          }}
          className={`absolute inset-0 w-full h-full object-cover transition-opacity duration-1000 ease-in-out scale-[1.02] ${
            !isDarkMode ? 'opacity-100' : 'opacity-0'
          }`}
          style={{
            objectPosition: '50% 50%'
          }}
        />

        {/* Dynamic ambient overlays to protect contrast on the right side where elements lay */}
        {isDarkMode ? (
          /* Starry Night Shade: Deep blue focus on the right */
          <div className="absolute inset-0 bg-gradient-to-r from-blue-950/10 via-[#070b25]/40 to-[#030514]/75 mix-blend-multiply" />
        ) : (
          /* Wheatfield Shade: Gentle warm focus on the right */
          <div className="absolute inset-0 bg-gradient-to-r from-[#e3f4fc]/5 via-[#dfdab4]/20 to-[#463f25]/50 mix-blend-multiply" />
        )}

        {/* Gentle background grain overlay simulating brush canvas weave */}
        <div 
          className="absolute inset-0 opacity-[0.18] mix-blend-overlay"
          style={{ 
            backgroundImage: 'repeating-linear-gradient(0deg, #ece0ca, #ece0ca 1.5px, transparent 1.5px, transparent 3px), repeating-linear-gradient(90deg, #ece0ca, #ece0ca 1.5px, transparent 1.5px, transparent 3px)'
          }} 
        />
      </div>

      {/* ================= STYLE CONTROL SWITCHER ================= */}
      <div className="absolute right-4 top-4 sm:right-6 sm:top-6 z-50">
        <button
          onClick={() => setIsDarkMode(!isDarkMode)}
          type="button"
          className={`flex items-center gap-1.5 px-3.5 py-2 rounded-full border text-xs font-bold cursor-pointer transition-all active:scale-95 duration-300 shadow-xl ${
            isDarkMode 
              ? 'bg-slate-950/85 border-slate-800/85 text-yellow-400 hover:bg-slate-900 shadow-black' 
              : 'bg-white/95 border-amber-200/60 text-amber-905 hover:bg-amber-50 shadow-amber-950/10'
          }`}
        >
          {isDarkMode ? (
            <>
              <Sun size={12} className="text-yellow-400 animate-spin" style={{ animationDuration: '40s' }} />
              <span>《麦田与柏树》亮色主题</span>
            </>
          ) : (
            <>
              <Moon size={12} className="text-indigo-800" />
              <span>《星月夜》暗色主题</span>
            </>
          )}
        </button>
      </div>

      {/* ================= RIGHT-ALIGNED GLASS SIDE BAR PANEL (Unobstructive design) ================= */}
      <div className="w-full md:w-[480px] h-full flex flex-col justify-center px-4 sm:px-12 md:px-16 relative z-40 transition-transform duration-500 overflow-y-auto">
        
        {/* Semi-transparent protective back drop that integrates naturally with split display */}
        <div className={`absolute inset-0 -z-10 transition-all duration-1000 ${
          isDarkMode 
            ? 'bg-gradient-to-l from-black/60 via-slate-950/30 to-transparent backdrop-blur-[6px]' 
            : 'bg-gradient-to-l from-amber-950/45 via-white/10 to-transparent backdrop-blur-[5px]'
        }`} />

        {/* Floating elements inside wrapper without bulky cards */}
        <div className="py-8 text-left w-full max-w-[340px] mx-auto md:mr-0 md:ml-auto">
          
          {/* Header Branding node */}
          <div className="flex items-center space-x-2.5 mb-8 select-none">
            <div className={`w-8.5 h-8.5 rounded-lg flex items-center justify-center text-sm font-bold shadow-md border ${
              isDarkMode 
                ? 'bg-gradient-to-tr from-sky-400 via-indigo-600 to-yellow-300 text-white border-white/10'
                : 'bg-gradient-to-tr from-amber-500 via-yellow-400 to-emerald-600 text-white border-amber-900/10'
            }`}>
              🪄
            </div>
            <div>
              <h4 className={`font-black text-xs tracking-widest ${isDarkMode ? 'text-white' : 'text-slate-900'}`}>
                AIMAGICIAN
              </h4>
              <p className={`text-[8px] font-mono tracking-widest leading-none ${isDarkMode ? 'text-sky-300' : 'text-amber-800 font-extrabold'}`}>
                {isDarkMode ? 'STARRY CONSOLE' : 'WHEATFIELD CONSOLE'}
              </p>
            </div>
          </div>

          <div className="space-y-1.5 mb-8 bg-transparent">
            <h3 className={`text-xl font-black tracking-tight flex items-center gap-2 ${
              isDarkMode ? 'text-white' : 'text-slate-900'
            }`}>
              <Feather size={18} className={isDarkMode ? 'text-yellow-400' : 'text-amber-700'} />
              <span>研写控制中心</span>
            </h3>
            <p className={`text-[11px] leading-relaxed ${isDarkMode ? 'text-slate-300' : 'text-slate-800 font-medium'}`}>
              欢迎登录，尊贵的管理员。该系统专供个人安全配置，输入安全密钥立刻激活创作中枢。
            </p>
          </div>

          {loading ? (
            /* Elegant interactive loading steps overlay */
            <div className="py-8 space-y-5 flex flex-col justify-center items-center rounded-2xl p-6 bg-black/10 backdrop-blur-md">
              <div className="relative w-11 h-11 flex items-center justify-center">
                <div className={`absolute inset-0 rounded-full border-2 border-t-transparent animate-spin ${
                  isDarkMode ? 'border-sky-400' : 'border-amber-700'
                }`} />
                <Cpu className={isDarkMode ? 'text-sky-400' : 'text-amber-700'} size={16} />
              </div>
              
              <div className="space-y-1 text-center">
                <span className="text-[8px] font-mono uppercase tracking-widest text-slate-400 font-bold block">
                  Credential Decrypting {loadingStep}/3
                </span>
                <p className={`text-xs font-bold min-h-[20px] px-1 transition-all duration-300 ${
                  isDarkMode ? 'text-sky-400 font-mono' : 'text-amber-700'
                }`}>
                  {loadingSteps[loadingStep]}
                </p>
              </div>
              
              <div className={`w-full max-w-[140px] h-1 rounded-full overflow-hidden ${isDarkMode ? 'bg-slate-850' : 'bg-slate-200'}`}>
                <div 
                  className={`h-full transition-all duration-300 ${isDarkMode ? 'bg-sky-400' : 'bg-amber-600'}`}
                  style={{ width: `${(loadingStep / 3) * 100}%` }}
                />
              </div>
            </div>
          ) : (
            <form onSubmit={handleLogin} className="space-y-5 font-sans">
              
              {error && (
                <div className="p-3.5 rounded-xl border border-rose-500/25 bg-rose-500/10 text-rose-300 text-xs flex items-center gap-1.5 font-semibold backdrop-blur-md">
                  <ShieldAlert size={12} className="shrink-0 text-rose-450" />
                  <span>{error}</span>
                </div>
              )}

              {/* Account/Email Field */}
              <div className="space-y-1.5">
                <label className={`text-[9.5px] font-extrabold font-mono uppercase tracking-widest block ${
                  isDarkMode ? 'text-slate-300' : 'text-slate-900'
                }`}>
                  管理员账号 (Email)
                </label>
                <div className="relative">
                  <span className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-400">
                    <Mail size={12} />
                  </span>
                  <input
                    type="text"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="请输入管理员大盘账户"
                    className={`w-full pl-9 pr-3.5 py-3 rounded-xl text-xs transition-all ${
                      isDarkMode
                        ? 'bg-slate-950/65 border-white/10 text-white placeholder-slate-500 focus:border-sky-400 focus:bg-slate-950/85'
                        : 'bg-white/60 border-amber-950/20 text-slate-950 placeholder-slate-700 focus:border-amber-900 focus:bg-white/90'
                    } focus:ring-4 focus:ring-amber-500/5 focus:outline-none`}
                  />
                </div>
              </div>

              {/* Password Field */}
              <div className="space-y-1.5">
                <label className={`text-[9.5px] font-extrabold font-mono uppercase tracking-widest block ${
                  isDarkMode ? 'text-slate-300' : 'text-slate-900'
                }`}>
                  安全验证授权码 (Access Code)
                </label>
                <div className="relative">
                  <span className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-400">
                    <Key size={12} />
                  </span>
                  <input
                    type={showPassword ? 'text' : 'password'}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="请输入授权访问密码"
                    className={`w-full pl-9 pr-12 py-3 rounded-xl text-xs transition-all ${
                      isDarkMode
                        ? 'bg-slate-950/65 border-white/10 text-white placeholder-slate-500 focus:border-sky-400 focus:bg-slate-950/85'
                        : 'bg-white/60 border-amber-950/20 text-slate-950 placeholder-slate-700 focus:border-amber-900 focus:bg-white/90'
                    } focus:ring-4 focus:ring-sky-500/5 focus:outline-none`}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className={`absolute inset-y-0 right-0 pr-3.5 flex items-center text-xs font-mono transition-colors ${
                      isDarkMode ? 'text-slate-400 hover:text-white' : 'text-slate-700 hover:text-slate-950'
                    }`}
                  >
                    {showPassword ? <EyeOff size={13} /> : <Eye size={13} />}
                  </button>
                </div>
              </div>

              {/* Quick Submit Direct Pathway */}
              <button
                type="submit"
                className={`w-full py-3 rounded-xl text-xs font-bold flex items-center justify-center gap-1.5 active:scale-95 transition-all cursor-pointer shadow-lg mt-4 ${
                  isDarkMode 
                    ? 'text-slate-950 bg-white hover:bg-slate-100 shadow-white/5' 
                    : 'text-white bg-slate-950 hover:bg-slate-900 shadow-slate-950/10'
                }`}
              >
                <span>解密凭证并登入中枢</span>
                <ArrowRight size={12} />
              </button>

            </form>
          )}

          {/* TLS security signal inside card */}
          <div className="mt-5.5 flex items-center justify-between border-t border-dashed border-gray-500/15 pt-4 text-[8.5px] font-mono text-gray-500">
            <span className="flex items-center gap-1.5">
              <CheckCircle2 size={10} className="text-emerald-500" />
              <span className={isDarkMode ? 'text-slate-400' : 'text-slate-800'}>TLS 通信防护及安全授权已就绪</span>
            </span>
          </div>

        </div>

      </div>

      {/* ================= FOOTER ================= */}
      <footer className="w-auto px-6 py-4 absolute bottom-4 left-6 z-30 text-[8.5px] font-mono text-white/50 bg-slate-950/30 backdrop-blur-md rounded-full px-4 py-1.5 hidden md:block">
        <span>AImagician Creative Console · Master Piece Edition © 2026</span>
      </footer>

    </div>
  );
}
