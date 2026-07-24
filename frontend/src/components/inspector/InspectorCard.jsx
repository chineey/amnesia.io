import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils';

export function InspectorCard({ icon, title, badge, children, className }) {
  return (
    <Card className={cn('gap-3 border-white/5 bg-black/20 p-4', className)}>
      <div className="flex items-center gap-2">
        {icon}
        <h4 className="font-heading text-sm font-medium">{title}</h4>
        {badge && <div className="ml-auto">{badge}</div>}
      </div>
      {children}
    </Card>
  );
}
