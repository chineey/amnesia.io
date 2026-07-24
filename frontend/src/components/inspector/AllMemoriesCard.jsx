import { Database } from 'lucide-react';
import { InspectorCard } from './InspectorCard';

export function AllMemoriesCard({ memories }) {
  return (
    <InspectorCard
      icon={<Database className="size-4 text-muted-foreground" />}
      title={`All Stored Episodic Chunks (${memories.length})`}
    >
      {memories.length === 0 ? (
        <p className="text-[13px] text-muted-foreground italic">
          No episodic memories stored in pgvector database yet.
        </p>
      ) : (
        <div className="flex flex-col gap-2">
          {memories.slice(0, 10).map((mem, i) => (
            <div key={i} className="rounded-lg border border-white/[0.04] bg-white/[0.02] p-2.5">
              <div className="mb-1 flex justify-between text-[10px] text-muted-foreground">
                <span>Confidence: {Math.round(mem.confidence * 100)}%</span>
                <span>Hits: {mem.access_count}</span>
              </div>
              <p className="text-xs text-muted-foreground">{mem.content}</p>
            </div>
          ))}
          {memories.length > 10 && (
            <p className="text-center text-[11px] text-muted-foreground">
              Showing 10 of {memories.length} memories
            </p>
          )}
        </div>
      )}
    </InspectorCard>
  );
}
