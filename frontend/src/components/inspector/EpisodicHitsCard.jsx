import { Clock } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { InspectorCard } from './InspectorCard';

export function EpisodicHitsCard({ retrievedEpisodes }) {
  return (
    <InspectorCard
      icon={<Clock className="size-4 text-cyan-400" />}
      title="Turn Semantic Hits"
      badge={
        retrievedEpisodes.length > 0 && (
          <Badge className="animate-pulse-glow border-cyan-400/20 bg-cyan-400/10 text-cyan-300" variant="outline">
            Active retrieval
          </Badge>
        )
      }
    >
      {retrievedEpisodes.length === 0 ? (
        <p className="text-[13px] text-muted-foreground italic">
          No episodic memories retrieved for the last message.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {retrievedEpisodes.map((ep, i) => (
            <li key={i} className="rounded-r-lg border-l-2 border-cyan-400 bg-cyan-400/[0.04] px-3 py-2">
              <span className="text-[13px] italic">&ldquo;{ep}&rdquo;</span>
            </li>
          ))}
        </ul>
      )}
    </InspectorCard>
  );
}
