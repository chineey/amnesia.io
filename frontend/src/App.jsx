import React, { useState, useEffect, useRef } from 'react';
import { 
  MessageSquare, 
  Database, 
  Cpu, 
  Trash2, 
  LogOut, 
  Layers, 
  Play, 
  CheckCircle, 
  RefreshCw, 
  AlertTriangle, 
  Sparkles, 
  Bookmark, 
  Clock, 
  Activity 
} from 'lucide-react';

// Help generate UUIDs if crypto.randomUUID is not available
function generateUUID() {
  if (typeof window !== 'undefined' && window.crypto && window.crypto.randomUUID) {
    return window.crypto.randomUUID();
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
    const r = Math.random() * 16 | 0, v = c === 'x' ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  });
}

export default function App() {
  // Session / User settings
  const [userId, setUserId] = useState(() => {
    const saved = localStorage.getItem('amnesia_user_id');
    if (saved) return saved;
    const newId = generateUUID();
    localStorage.setItem('amnesia_user_id', newId);
    return newId;
  });

  const [sessionId, setSessionId] = useState(() => generateUUID());
  const [sessionCount, setSessionCount] = useState(1);
  const [activePanel, setActivePanel] = useState('chat'); // 'chat' | 'eval'
  const [mobileSubTab, setMobileSubTab] = useState('chat'); // 'chat' | 'inspector'

  // Chat state
  const [messages, setMessages] = useState([]);
  const [inputText, setInputText] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);

  // Memory Inspector states (from SSE metadata)
  const [coreProfile, setCoreProfile] = useState({ facts: [], preferences: [], events: [] });
  const [retrievedEpisodes, setRetrievedEpisodes] = useState([]);
  const [tokenStats, setTokenStats] = useState(null);
  const [redisHistory, setRedisHistory] = useState([]);
  
  // Historical episodic list (all of them)
  const [allEpisodicMemories, setAllEpisodicMemories] = useState([]);

  // Eval states
  const [evalLogs, setEvalLogs] = useState([]);
  const [evalRunning, setEvalRunning] = useState(false);
  const [evalProgress, setEvalProgress] = useState(0);

  const messagesEndRef = useRef(null);

  // Load profile and all memories on startup/session change
  const refreshMemoryInspector = async () => {
    try {
      const profileRes = await fetch(`/api/profile?user_id=${userId}`);
      if (profileRes.ok) {
        const profileData = await profileRes.json();
        setCoreProfile(profileData);
      }

      const memoriesRes = await fetch(`/api/memories?user_id=${userId}`);
      if (memoriesRes.ok) {
        const memoriesData = await memoriesRes.json();
        setAllEpisodicMemories(memoriesData);
      }
    } catch (err) {
      console.error("Error refreshing memory inspector:", err);
    }
  };

  useEffect(() => {
    refreshMemoryInspector();
  }, [userId, sessionId]);

  useEffect(() => {
    // Scroll to bottom of chat
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // SSE Chat stream handler
  const handleSendMessage = async (e) => {
    e?.preventDefault();
    if (!inputText.trim() || isStreaming) return;

    const userText = inputText;
    setInputText('');

    // Append user message local view
    setMessages(prev => [...prev, { role: 'user', content: userText }]);
    setIsStreaming(true);

    // Append placeholder for assistant streaming
    setMessages(prev => [...prev, { role: 'assistant', content: '' }]);

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          user_id: userId,
          session_id: sessionId,
          message: userText
        })
      });

      if (!response.ok) {
        throw new Error(`Chat API error: ${response.statusText}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let assistantResponse = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split('\n');
        
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const dataStr = line.slice(6).trim();
            if (!dataStr) continue;

            try {
              const data = JSON.parse(dataStr);
              if (data.type === 'metadata') {
                // Set memory inspector details from backend retrieval layer
                setCoreProfile(data.core_profile);
                setRetrievedEpisodes(data.retrieved_episodes);
                setTokenStats(data.token_stats);
                setRedisHistory(data.redis_history);
              } else if (data.type === 'token') {
                assistantResponse += data.content;
                // Update the last message in array (which is the assistant message)
                setMessages(prev => {
                  const updated = [...prev];
                  updated[updated.length - 1] = { role: 'assistant', content: assistantResponse };
                  return updated;
                });
              } else if (data.type === 'done') {
                // Done streaming
              }
            } catch (err) {
              // Occasional JSON parsing glitches for unfinished buffers, ignore
            }
          }
        }
      }
    } catch (err) {
      console.error(err);
      setMessages(prev => {
        const updated = [...prev];
        updated[updated.length - 1] = { role: 'assistant', content: `[Error: Failed to fetch response. Make sure backend is running.]` };
        return updated;
      });
    } finally {
      setIsStreaming(false);
      // Refresh historical episodic list
      refreshMemoryInspector();
    }
  };

  // Trigger End of Session (Path B)
  const handleEndSession = async () => {
    if (confirm("This will end the current session, run Gemini's extraction/contradiction pass to update your Core Profile, and clear active working memory. Continue?")) {
      try {
        const response = await fetch('/api/session/end', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_id: userId, session_id: sessionId })
        });
        
        if (response.ok) {
          alert("Session teardown triggered in background! Core Profile will update in a few seconds.");
          // Wait 3 seconds, then start a new session & refresh
          setTimeout(() => {
            const newSessId = generateUUID();
            setSessionId(newSessId);
            setSessionCount(prev => prev + 1);
            setMessages([]);
            setRetrievedEpisodes([]);
            setTokenStats(null);
            setRedisHistory([]);
            refreshMemoryInspector();
          }, 3500);
        }
      } catch (err) {
        alert("Failed to end session: " + err);
      }
    }
  };

  // Reset/Clear memories
  const handlePurgeMemories = async () => {
    if (confirm("WARNING: This will permanently delete ALL core profile entries and episodic memories for this user. Continue?")) {
      try {
        const response = await fetch(`/api/memories?user_id=${userId}`, {
          method: 'DELETE'
        });
        if (response.ok) {
          alert("All memories deleted!");
          setMessages([]);
          setCoreProfile({ facts: [], preferences: [], events: [] });
          setRetrievedEpisodes([]);
          setTokenStats(null);
          setRedisHistory([]);
          setAllEpisodicMemories([]);
        }
      } catch (err) {
        alert("Purge failed: " + err);
      }
    }
  };

  // Run the Simulation (Eval harness)
  const triggerSimulation = async () => {
    setEvalRunning(true);
    setEvalLogs([]);
    setEvalProgress(0);
    
    try {
      const response = await fetch('/api/eval/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId })
      });
      
      if (!response.ok) {
        throw new Error("Failed to run simulation");
      }
      
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        
        const chunk = decoder.decode(value);
        const lines = chunk.split('\n');
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const dataStr = line.slice(6).trim();
            if (!dataStr) continue;
            
            try {
              const logData = JSON.parse(dataStr);
              if (logData.type === 'log') {
                setEvalLogs(prev => [...prev, logData.message]);
              } else if (logData.type === 'progress') {
                setEvalProgress(logData.percent);
              } else if (logData.type === 'result') {
                setEvalLogs(prev => [...prev, `Simulation Finished!\nAverage Personalization Score: ${logData.avg_score}/10`]);
              }
            } catch (e) {}
          }
        }
      }
    } catch (err) {
      setEvalLogs(prev => [...prev, `[Error running simulation: ${err.message}]`]);
    } finally {
      setEvalRunning(false);
      refreshMemoryInspector();
    }
  };

  return (
    <div className="app-container">
      {/* Top Header Navbar */}
      <header className="header glass">
        <div className="header-left">
          <div style={styles.logoCircle}>
            <Activity size={20} color="#22d3ee" />
          </div>
          <div>
            <h1 className="brand-title">amnesia.io <span className="beta-tag">MemoryAgent</span></h1>
            <p className="brand-subtitle">Powered by Google Gemini & Neon</p>
          </div>
        </div>

        <div className="header-right">
          <div className="status-pill">
            <span style={styles.statusDot}></span>
            <span className="status-text">Local Node Running</span>
          </div>

          <div className="nav-tabs">
            <button 
              onClick={() => setActivePanel('chat')} 
              className={`nav-button ${activePanel === 'chat' ? 'active' : ''}`}
            >
              <MessageSquare size={16} />
              <span>Chat Playground</span>
            </button>
            <button 
              onClick={() => setActivePanel('eval')} 
              className={`nav-button ${activePanel === 'eval' ? 'active' : ''}`}
            >
              <Layers size={16} />
              <span>Evaluation Harness</span>
            </button>
          </div>

          <button 
            onClick={handleEndSession} 
            className="action-btn action-btn-end" 
            title="End current session, trigger contradiction resolution and start new session"
          >
            <LogOut size={15} />
            <span>End Session {sessionCount}</span>
          </button>

          <button 
            onClick={handlePurgeMemories} 
            className="action-btn action-btn-purge" 
            title="Clear all stored database tables for this user"
          >
            <Trash2 size={15} />
            <span>Purge Memory</span>
          </button>
        </div>
      </header>

      {/* Main Workspace Split Grid */}
      <main className="main-layout">
        {activePanel === 'chat' ? (
          <>
            {/* Mobile Sub-tab Switcher */}
            <div className="mobile-subtabs glass">
              <button 
                type="button"
                onClick={() => setMobileSubTab('chat')} 
                className={`mobile-subtab-btn ${mobileSubTab === 'chat' ? 'active' : ''}`}
              >
                <MessageSquare size={16} />
                <span>Playground</span>
              </button>
              <button 
                type="button"
                onClick={() => setMobileSubTab('inspector')} 
                className={`mobile-subtab-btn ${mobileSubTab === 'inspector' ? 'active' : ''}`}
              >
                <Database size={16} />
                <span>Inspector</span>
              </button>
            </div>

            {/* Left: Chat Widget */}
            <section className={`chat-section glass ${mobileSubTab === 'chat' ? 'mobile-visible' : 'mobile-hidden'}`}>
              <div className="chat-header">
                <div className="chat-header-info">
                  <MessageSquare size={18} color="#818cf8" />
                  <h3>Active Turn Stream</h3>
                  <span style={styles.sessIdText}>Session: {sessionId.slice(0, 8)}...</span>
                </div>
                <div className="chat-header-tip">
                  <Sparkles size={14} color="#22d3ee" />
                  <span>Gemini context updates session-by-session</span>
                </div>
              </div>

              {/* Chat Thread */}
              <div className="chat-messages-container">
                {messages.length === 0 ? (
                  <div style={styles.emptyChatPlaceholder}>
                    <Cpu size={48} color="#64748b" style={{marginBottom: 16}} />
                    <h4>Start a conversation with amnesia.io</h4>
                    <p style={{maxWidth: 360, marginTop: 8}}>
                      Introduce yourself, declare some coding preferences, and tell amnesia.io about your current projects. 
                      Then click <b>End Session</b> to watch it build your Core Profile!
                    </p>
                  </div>
                ) : (
                  messages.map((msg, idx) => (
                    <div 
                      key={idx} 
                      style={msg.role === 'user' ? styles.chatMsgUserRow : styles.chatMsgAssRow}
                      className="animate-slide-up"
                    >
                      <div className={msg.role === 'user' ? "chat-msg-user-bubble" : "chat-msg-ass-bubble"}>
                        <div style={styles.bubbleHeader}>
                          <strong>{msg.role === 'user' ? 'You' : 'amnesia.io'}</strong>
                        </div>
                        <p style={styles.bubbleText}>{msg.content || (isStreaming && idx === messages.length - 1 ? "Typing..." : "")}</p>
                      </div>
                    </div>
                  ))
                )}
                <div ref={messagesEndRef} />
              </div>

              {/* Chat Form */}
              <form onSubmit={handleSendMessage} className="chat-input-form">
                <input
                  type="text"
                  value={inputText}
                  onChange={(e) => setInputText(e.target.value)}
                  placeholder="Tell amnesia.io your language preferences or build profile..."
                  style={styles.chatInput}
                  disabled={isStreaming}
                />
                <button 
                  type="submit" 
                  style={styles.sendButton} 
                  disabled={isStreaming || !inputText.trim()}
                >
                  {isStreaming ? <RefreshCw size={16} className="animate-spin" /> : "Send"}
                </button>
              </form>
            </section>

            {/* Right: Memory Inspector Panel */}
            <section className={`inspector-section glass ${mobileSubTab === 'inspector' ? 'mobile-visible' : 'mobile-hidden'}`}>
              <div className="inspector-header">
                <Database size={18} color="#22d3ee" />
                <h3>Memory Inspector</h3>
                <span style={styles.badgeProfile}>Active profile: terrawimm</span>
              </div>

              <div className="inspector-scroll">
                {/* 1. Core Profile */}
                <div style={styles.inspectCard} className="glass">
                  <div style={styles.cardHeader}>
                    <Bookmark size={16} color="#c084fc" />
                    <h4>Core User Profile</h4>
                    <span style={styles.cardBadgeAlways}>Always Injected</span>
                  </div>
                  
                  {(!coreProfile.facts?.length && !coreProfile.preferences?.length) ? (
                    <p style={styles.emptyText}>No core profile extracted yet. End a session to trigger extraction.</p>
                  ) : (
                    <div style={styles.profileLists}>
                      {coreProfile.facts?.length > 0 && (
                        <div style={styles.profileSection}>
                          <h5 style={{color: '#818cf8'}}>Facts</h5>
                          <ul style={styles.profileList}>
                            {coreProfile.facts.map((f, i) => (
                              <li key={i} style={styles.profileItem}>
                                <span>{f.content}</span>
                                <span style={styles.confBadge}>{Math.round(f.confidence * 100)}%</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {coreProfile.preferences?.length > 0 && (
                        <div style={styles.profileSection}>
                          <h5 style={{color: '#c084fc'}}>Preferences</h5>
                          <ul style={styles.profileList}>
                            {coreProfile.preferences.map((p, i) => (
                              <li key={i} style={styles.profileItem}>
                                <span>{p.content}</span>
                                <span style={styles.confBadge}>{Math.round(p.confidence * 100)}%</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {/* 2. Retrieved Episodic Memories */}
                <div style={styles.inspectCard} className="glass">
                  <div style={styles.cardHeader}>
                    <Clock size={16} color="#22d3ee" />
                    <h4>Turn Semantic Hits</h4>
                    {retrievedEpisodes.length > 0 && <span style={styles.hitGlow}>Active Retrieval</span>}
                  </div>
                  {retrievedEpisodes.length === 0 ? (
                    <p style={styles.emptyText}>No episodic memories retrieved for the last message.</p>
                  ) : (
                    <ul style={styles.episodeList}>
                      {retrievedEpisodes.map((ep, i) => (
                        <li key={i} style={styles.episodeItem}>
                          <span style={styles.episodeQuote}>"{ep}"</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                {/* 3. Token Budget Capacity */}
                <div style={styles.inspectCard} className="glass">
                  <div style={styles.cardHeader}>
                    <Cpu size={16} color="#34d399" />
                    <h4>Token Cap Enforcement</h4>
                  </div>
                  {tokenStats ? (
                    <div style={styles.tokenStatsContainer}>
                      <div style={styles.progressBarWrapper}>
                        <div 
                          style={{
                            ...styles.progressBarFill, 
                            width: `${(tokenStats.total_used / tokenStats.total_cap) * 100}%`,
                            backgroundColor: tokenStats.total_used > 700 ? '#f87171' : '#34d399'
                          }}
                        />
                      </div>
                      <div style={styles.tokenDetails}>
                        <div style={styles.tokenStatRow}>
                          <span>Total Context Limit</span>
                          <strong>{tokenStats.total_cap} tokens</strong>
                        </div>
                        <div style={styles.tokenStatRow}>
                          <span>Core Profile Injected</span>
                          <span>{tokenStats.profile_tokens} tokens</span>
                        </div>
                        <div style={styles.tokenStatRow}>
                          <span>Redis History Tail</span>
                          <span>{tokenStats.working_memory_injected} tokens</span>
                        </div>
                        <div style={styles.tokenStatRow}>
                          <span>Semantic Episodic Injected</span>
                          <span>{tokenStats.episodic_tokens} tokens</span>
                        </div>
                        <div style={styles.tokenStatRow}>
                          <span>Remaining Budget</span>
                          <strong>{tokenStats.remaining_tokens} tokens</strong>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <p style={styles.emptyText}>Send a message to view token allocation stats.</p>
                  )}
                </div>

                {/* 4. Total Episodic Memories list (all history) */}
                <div style={styles.inspectCard} className="glass">
                  <div style={styles.cardHeader}>
                    <Database size={16} color="#94a3b8" />
                    <h4>All Stored Episodic Chunks ({allEpisodicMemories.length})</h4>
                  </div>
                  {allEpisodicMemories.length === 0 ? (
                    <p style={styles.emptyText}>No episodic memories stored in pgvector database yet.</p>
                  ) : (
                    <div style={styles.memoriesGrid}>
                      {allEpisodicMemories.slice(0, 10).map((mem, i) => (
                        <div key={i} style={styles.memoryTile}>
                          <div style={styles.memoryTileMeta}>
                            <span>Confidence: {Math.round(mem.confidence * 100)}%</span>
                            <span>Hits: {mem.access_count}</span>
                          </div>
                          <p style={styles.memoryTileContent}>{mem.content}</p>
                        </div>
                      ))}
                      {allEpisodicMemories.length > 10 && (
                        <p style={{fontSize: 11, color: 'var(--text-muted)', textAlign: 'center'}}>Showing 10 of {allEpisodicMemories.length} memories</p>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </section>
          </>
        ) : (
          /* Evaluation Harness Dashboard Panel */
          <section className="eval-container glass">
            <div className="eval-header">
              <div style={{display: 'flex', alignItems: 'center', gap: 12}}>
                <Layers size={24} color="#818cf8" />
                <div>
                  <h3>Evaluation & Simulation Harness</h3>
                  <p style={{fontSize: 13, color: 'var(--text-secondary)'}}>Simulate a synthetic user journey across 5 distinct sessions to measure customization performance and memory decay.</p>
                </div>
              </div>
              
              <button 
                onClick={triggerSimulation} 
                className="run-sim-button" 
                disabled={evalRunning}
              >
                <Play size={16} />
                <span>{evalRunning ? 'Running Simulation...' : 'Run 5-Session Simulation'}</span>
              </button>
            </div>

            {evalRunning && (
              <div style={styles.progressBarContainer}>
                <div style={{...styles.progressBarProgress, width: `${evalProgress}%`}} />
              </div>
            )}

            <div className="eval-terminal">
              <div style={styles.terminalHeader}>
                <span style={styles.terminalDotRed}></span>
                <span style={styles.terminalDotYellow}></span>
                <span style={styles.terminalDotGreen}></span>
                <span style={styles.terminalTitle}>amnesia.io Simulation Logs</span>
              </div>
              <div style={styles.terminalBody}>
                {evalLogs.length === 0 ? (
                  <div style={styles.terminalEmpty}>
                    <Cpu size={40} color="#334155" style={{marginBottom: 12}} />
                    <span>Waiting to run synthetic simulation. Click the button above to begin.</span>
                  </div>
                ) : (
                  evalLogs.map((log, i) => (
                    <pre key={i} style={styles.terminalLine}>{log}</pre>
                  ))
                )}
              </div>
            </div>
          </section>
        )}
      </main>
    </div>
  );
}

// Inline HSL premium styles
const styles = {
  appContainer: {
    display: 'flex',
    flexDirection: 'column',
    height: '100vh',
    padding: '16px',
    gap: '16px',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '12px 24px',
    height: '70px',
  },
  headerLeft: {
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
  },
  logoCircle: {
    width: '36px',
    height: '36px',
    borderRadius: '50%',
    background: 'rgba(34, 211, 238, 0.1)',
    border: '1px solid rgba(34, 211, 238, 0.2)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  },
  brandTitle: {
    fontFamily: 'var(--font-display)',
    fontSize: '20px',
    fontWeight: '700',
    color: '#fff',
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
  },
  betaTag: {
    fontSize: '10px',
    padding: '2px 6px',
    borderRadius: '10px',
    background: 'linear-gradient(135deg, var(--color-primary-dark), #6366f1)',
    color: '#fff',
    fontWeight: 'bold',
  },
  brandSubtitle: {
    fontSize: '11px',
    color: 'var(--text-secondary)',
  },
  headerRight: {
    display: 'flex',
    alignItems: 'center',
    gap: '16px',
  },
  statusPill: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    padding: '6px 12px',
    borderRadius: '20px',
    background: 'rgba(255,255,255,0.03)',
    border: '1px solid var(--border-color)',
    fontSize: '12px',
    color: 'var(--text-secondary)',
  },
  statusDot: {
    width: '8px',
    height: '8px',
    borderRadius: '50%',
    backgroundColor: 'var(--success)',
    boxShadow: '0 0 8px var(--success)',
  },
  navTabs: {
    display: 'flex',
    background: 'rgba(0,0,0,0.2)',
    padding: '4px',
    borderRadius: '10px',
    border: '1px solid var(--border-color)',
  },
  navButton: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    padding: '6px 14px',
    borderRadius: '8px',
    color: 'var(--text-secondary)',
    fontSize: '13px',
  },
  navButtonActive: {
    background: 'var(--bg-card)',
    color: '#fff',
    border: '1px solid var(--border-color-active)',
  },
  actionBtnEnd: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    padding: '8px 16px',
    borderRadius: '10px',
    background: 'linear-gradient(135deg, var(--color-primary-dark), #3b82f6)',
    color: '#fff',
    fontSize: '13px',
    fontWeight: '600',
  },
  actionBtnPurge: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    padding: '8px 12px',
    borderRadius: '10px',
    border: '1px solid rgba(248, 113, 113, 0.2)',
    color: 'var(--danger)',
    fontSize: '13px',
  },
  mainLayout: {
    display: 'grid',
    gridTemplateColumns: '60% 40%',
    flex: 1,
    gap: '16px',
    height: 'calc(100vh - 120px)',
    overflow: 'hidden',
  },
  chatSection: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    overflow: 'hidden',
  },
  chatHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '16px 20px',
    borderBottom: '1px solid var(--border-color)',
  },
  chatHeaderInfo: {
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
  },
  sessIdText: {
    fontSize: '11px',
    color: 'var(--text-muted)',
    background: 'rgba(255,255,255,0.03)',
    padding: '2px 6px',
    borderRadius: '4px',
  },
  chatHeaderTip: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    fontSize: '12px',
    color: 'var(--text-secondary)',
  },
  chatMessagesContainer: {
    flex: 1,
    padding: '20px',
    overflowY: 'auto',
    display: 'flex',
    flexDirection: 'column',
    gap: '20px',
  },
  emptyChatPlaceholder: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    height: '100%',
    color: 'var(--text-secondary)',
    textAlign: 'center',
  },
  chatMsgUserRow: {
    display: 'flex',
    justifyContent: 'flex-end',
  },
  chatMsgAssRow: {
    display: 'flex',
    justifyContent: 'flex-start',
  },
  chatMsgUserBubble: {
    background: 'linear-gradient(135deg, #1e293b, #0f172a)',
    border: '1px solid rgba(255,255,255,0.05)',
    padding: '12px 16px',
    borderRadius: '16px 16px 4px 16px',
    maxWidth: '80%',
  },
  chatMsgAssBubble: {
    background: 'rgba(30, 41, 59, 0.3)',
    border: '1px solid var(--border-color)',
    padding: '12px 16px',
    borderRadius: '16px 16px 16px 4px',
    maxWidth: '80%',
  },
  bubbleHeader: {
    fontSize: '11px',
    color: 'var(--text-secondary)',
    marginBottom: '4px',
  },
  bubbleText: {
    fontSize: '14px',
    color: 'var(--text-primary)',
    whiteSpace: 'pre-wrap',
  },
  chatInputForm: {
    padding: '16px 20px',
    borderTop: '1px solid var(--border-color)',
    display: 'flex',
    gap: '12px',
    background: 'rgba(0,0,0,0.15)',
  },
  chatInput: {
    flex: 1,
    background: 'rgba(15, 23, 42, 0.6)',
    border: '1px solid var(--border-color)',
    borderRadius: '10px',
    padding: '12px 16px',
    color: '#fff',
    fontFamily: 'var(--font-sans)',
    fontSize: '14px',
    outline: 'none',
    transition: 'border-color 0.2s',
  },
  sendButton: {
    background: 'linear-gradient(135deg, #6366f1, #4f46e5)',
    color: '#fff',
    padding: '0 24px',
    borderRadius: '10px',
    fontSize: '14px',
    fontWeight: '600',
  },
  inspectorSection: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    overflow: 'hidden',
    borderLeft: '1px solid var(--border-color)',
  },
  inspectorHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
    padding: '16px 20px',
    borderBottom: '1px solid var(--border-color)',
  },
  badgeProfile: {
    fontSize: '11px',
    padding: '2px 8px',
    background: 'rgba(34, 211, 238, 0.1)',
    color: 'var(--color-accent)',
    borderRadius: '12px',
    marginLeft: 'auto',
  },
  inspectorScroll: {
    flex: 1,
    padding: '20px',
    overflowY: 'auto',
    display: 'flex',
    flexDirection: 'column',
    gap: '16px',
  },
  inspectCard: {
    padding: '16px',
    background: 'rgba(15, 23, 42, 0.3)',
  },
  cardHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    marginBottom: '12px',
  },
  cardBadgeAlways: {
    fontSize: '10px',
    padding: '1px 6px',
    background: 'rgba(251, 191, 36, 0.1)',
    color: 'var(--warning)',
    borderRadius: '4px',
    marginLeft: 'auto',
  },
  hitGlow: {
    fontSize: '10px',
    padding: '1px 6px',
    background: 'rgba(34, 211, 238, 0.1)',
    color: 'var(--color-accent)',
    borderRadius: '4px',
    marginLeft: 'auto',
    animation: 'pulseGlow 2s infinite ease-in-out',
  },
  emptyText: {
    fontSize: '13px',
    color: 'var(--text-muted)',
    fontStyle: 'italic',
  },
  profileLists: {
    display: 'flex',
    flexDirection: 'column',
    gap: '12px',
  },
  profileSection: {
    display: 'flex',
    flexDirection: 'column',
    gap: '6px',
  },
  profileList: {
    listStyle: 'none',
    display: 'flex',
    flexDirection: 'column',
    gap: '6px',
  },
  profileItem: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    background: 'rgba(255,255,255,0.02)',
    padding: '8px 12px',
    borderRadius: '8px',
    fontSize: '13px',
    border: '1px solid rgba(255,255,255,0.02)',
  },
  confBadge: {
    fontSize: '10px',
    background: 'rgba(255,255,255,0.05)',
    color: 'var(--text-secondary)',
    padding: '2px 6px',
    borderRadius: '4px',
  },
  episodeList: {
    listStyle: 'none',
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
  },
  episodeItem: {
    padding: '8px 12px',
    background: 'rgba(34, 211, 238, 0.03)',
    borderLeft: '2px solid var(--color-accent)',
    borderRadius: '0 8px 8px 0',
  },
  episodeQuote: {
    fontSize: '13px',
    fontStyle: 'italic',
    color: 'var(--text-primary)',
  },
  tokenStatsContainer: {
    display: 'flex',
    flexDirection: 'column',
    gap: '12px',
  },
  progressBarWrapper: {
    height: '8px',
    background: 'rgba(255,255,255,0.05)',
    borderRadius: '4px',
    overflow: 'hidden',
  },
  progressBarFill: {
    height: '100%',
    borderRadius: '4px',
    transition: 'width 0.5s ease-out',
  },
  tokenDetails: {
    display: 'flex',
    flexDirection: 'column',
    gap: '6px',
    fontSize: '12px',
  },
  tokenStatRow: {
    display: 'flex',
    justifyContent: 'space-between',
    color: 'var(--text-secondary)',
  },
  memoriesGrid: {
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
  },
  memoryTile: {
    background: 'rgba(255,255,255,0.02)',
    border: '1px solid rgba(255,255,255,0.04)',
    borderRadius: '8px',
    padding: '10px',
  },
  memoryTileMeta: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: '10px',
    color: 'var(--text-muted)',
    marginBottom: '4px',
  },
  memoryTileContent: {
    fontSize: '12px',
    color: 'var(--text-secondary)',
  },
  evalContainer: {
    gridColumn: '1 / span 2',
    height: '100%',
    padding: '30px',
    display: 'flex',
    flexDirection: 'column',
    gap: '24px',
  },
  evalHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  runSimButton: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    padding: '12px 24px',
    borderRadius: '10px',
    background: 'linear-gradient(135deg, var(--color-primary-dark), #6366f1)',
    color: '#fff',
    fontSize: '14px',
    fontWeight: '600',
  },
  progressBarContainer: {
    height: '6px',
    background: 'rgba(255,255,255,0.05)',
    borderRadius: '3px',
    overflow: 'hidden',
  },
  progressBarProgress: {
    height: '100%',
    background: 'var(--color-accent)',
    borderRadius: '3px',
    transition: 'width 0.4s ease',
  },
  evalTerminal: {
    flex: 1,
    background: '#040711',
    border: '1px solid var(--border-color)',
    borderRadius: '12px',
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
  },
  terminalHeader: {
    background: '#0a0d1a',
    padding: '10px 16px',
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    borderBottom: '1px solid var(--border-color)',
  },
  terminalDotRed: { width: '10px', height: '10px', borderRadius: '50%', backgroundColor: '#f87171' },
  terminalDotYellow: { width: '10px', height: '10px', borderRadius: '50%', backgroundColor: '#fbbf24' },
  terminalDotGreen: { width: '10px', height: '10px', borderRadius: '50%', backgroundColor: '#34d399' },
  terminalTitle: {
    fontSize: '11px',
    color: 'var(--text-muted)',
    fontFamily: 'var(--font-mono)',
    marginLeft: '12px',
  },
  terminalBody: {
    flex: 1,
    padding: '16px',
    overflowY: 'auto',
    fontFamily: 'var(--font-mono)',
    fontSize: '12px',
    color: '#34d399',
    display: 'flex',
    flexDirection: 'column',
    gap: '6px',
  },
  terminalEmpty: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    height: '100%',
    color: 'var(--text-muted)',
  },
  terminalLine: {
    whiteSpace: 'pre-wrap',
    lineHeight: '1.6',
    borderBottom: '1px dashed rgba(52, 211, 153, 0.05)',
    paddingBottom: '4px',
  }
};
