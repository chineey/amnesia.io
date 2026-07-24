import { useState } from 'react';
import { Database, MessageSquare } from 'lucide-react';
import { Tabs, TabsContent } from '@/components/ui/tabs';
import { TooltipProvider } from '@/components/ui/tooltip';
import { Toaster } from '@/components/ui/sonner';
import { Button } from '@/components/ui/button';
import { AppHeader } from '@/components/layout/AppHeader';
import { ChatPanel } from '@/components/chat/ChatPanel';
import { MemoryInspector } from '@/components/inspector/MemoryInspector';
import { EvalPanel } from '@/components/eval/EvalPanel';
import { useChat } from '@/hooks/useChat';
import { useMemoryInspector } from '@/hooks/useMemoryInspector';
import { useEvalRun } from '@/hooks/useEvalRun';
import { endSession as endSessionApi, purgeMemories as purgeMemoriesApi } from '@/lib/api';
import { generateUUID, cn } from '@/lib/utils';

const SESSION_TEARDOWN_DELAY_MS = 3500;

export default function App() {
  const [userId] = useState(() => {
    const saved = localStorage.getItem('amnesia_user_id');
    if (saved) return saved;
    const newId = generateUUID();
    localStorage.setItem('amnesia_user_id', newId);
    return newId;
  });

  const [sessionId, setSessionId] = useState(() => generateUUID());
  const [sessionCount, setSessionCount] = useState(1);
  const [activePanel, setActivePanel] = useState('chat');
  const [mobilePane, setMobilePane] = useState('chat'); // 'chat' | 'inspector'
  const [inputText, setInputText] = useState('');

  const inspector = useMemoryInspector(userId, sessionId);
  const chat = useChat({
    userId,
    sessionId,
    onMetadata: inspector.setCoreProfile,
    onSettled: inspector.refresh,
  });
  const evalRun = useEvalRun({ userId, onSettled: inspector.refresh });

  const handleEndSession = async () => {
    await endSessionApi(userId, sessionId);
    setTimeout(() => {
      setSessionId(generateUUID());
      setSessionCount((c) => c + 1);
      chat.resetChat();
      inspector.refresh();
    }, SESSION_TEARDOWN_DELAY_MS);
  };

  const handlePurgeMemories = async () => {
    await purgeMemoriesApi(userId);
    chat.resetChat();
    inspector.reset();
  };

  return (
    <TooltipProvider>
      <Tabs
        value={activePanel}
        onValueChange={setActivePanel}
        className="h-screen gap-4 overflow-hidden p-3 sm:p-4"
      >
        <AppHeader
          sessionCount={sessionCount}
          onEndSession={handleEndSession}
          onPurgeMemories={handlePurgeMemories}
        />

        <main className="min-h-0 flex-1">
          <TabsContent value="chat" className="flex h-full flex-col gap-3">
            <div className="flex gap-2 md:hidden">
              <Button
                variant={mobilePane === 'chat' ? 'secondary' : 'ghost'}
                size="sm"
                className="flex-1 gap-1.5"
                onClick={() => setMobilePane('chat')}
              >
                <MessageSquare className="size-3.5" /> Playground
              </Button>
              <Button
                variant={mobilePane === 'inspector' ? 'secondary' : 'ghost'}
                size="sm"
                className="flex-1 gap-1.5"
                onClick={() => setMobilePane('inspector')}
              >
                <Database className="size-3.5" /> Inspector
              </Button>
            </div>

            <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 md:grid-cols-[60%_40%]">
              <ChatPanel
                className={cn(mobilePane !== 'chat' && 'hidden md:flex')}
                messages={chat.messages}
                isStreaming={chat.isStreaming}
                inputText={inputText}
                setInputText={setInputText}
                onSend={chat.sendMessage}
                sessionId={sessionId}
              />
              <MemoryInspector
                className={cn(mobilePane !== 'inspector' && 'hidden md:flex')}
                coreProfile={inspector.coreProfile}
                retrievedEpisodes={chat.retrievedEpisodes}
                tokenStats={chat.tokenStats}
                allEpisodicMemories={inspector.allEpisodicMemories}
              />
            </div>
          </TabsContent>

          <TabsContent value="eval" className="h-full">
            <EvalPanel
              logs={evalRun.logs}
              running={evalRun.running}
              progress={evalRun.progress}
              onRun={evalRun.run}
            />
          </TabsContent>
        </main>
      </Tabs>
      <Toaster />
    </TooltipProvider>
  );
}
