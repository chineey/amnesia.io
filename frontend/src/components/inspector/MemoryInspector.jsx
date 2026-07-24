import { Database } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import { CoreProfileCard } from './CoreProfileCard';
import { EpisodicHitsCard } from './EpisodicHitsCard';
import { TokenBudgetCard } from './TokenBudgetCard';
import { AllMemoriesCard } from './AllMemoriesCard';
import { cn } from '@/lib/utils';

export function MemoryInspector({ coreProfile, retrievedEpisodes, tokenStats, allEpisodicMemories, className }) {
  return (
    <Card className={cn('glass flex h-full flex-col gap-0 overflow-hidden border-l border-border py-0', className)}>
      <div className="flex shrink-0 items-center gap-2.5 border-b border-border px-5 py-4">
        <Database className="size-4.5 text-cyan-400" />
        <h3 className="font-heading text-sm font-semibold">Memory Inspector</h3>
      </div>

      <ScrollArea className="min-h-0 flex-1">
        <div className="flex flex-col gap-4 p-5">
          <CoreProfileCard coreProfile={coreProfile} />
          <EpisodicHitsCard retrievedEpisodes={retrievedEpisodes} />
          <TokenBudgetCard tokenStats={tokenStats} />
          <AllMemoriesCard memories={allEpisodicMemories} />
        </div>
      </ScrollArea>
    </Card>
  );
}
