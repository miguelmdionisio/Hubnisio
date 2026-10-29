import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowDown, ArrowUp, Pencil, Play, Plus, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';
import {
  deleteRuleMutation,
  listRulesOptions,
  listRulesQueryKey,
  reorderRulesMutation,
  runRulesMutation,
  updateRuleMutation,
} from '@/api/@tanstack/react-query.gen';
import type { RuleOut } from '@/api/types.gen';
import { PageHeader } from '@/components/app-shell';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Skeleton } from '@/components/ui/skeleton';
import { Switch } from '@/components/ui/switch';
import { errorMessage } from '@/lib/errors';
import { categoryNames, useCategories } from './category-picker';
import { useMerchants } from './merchant-picker';
import { RuleEditor } from './rule-editor';
import { describeAction, describeCondition, type Names, ruleToInput } from './rule-model';
import { useAccounts } from './use-accounts';
import { invalidateUserLayer } from './use-transaction-edits';

export function RulesPage() {
  const queryClient = useQueryClient();
  const rules = useQuery(listRulesOptions());
  const accounts = useAccounts();
  const categories = useCategories();
  const merchants = useMerchants();
  const [editing, setEditing] = useState<RuleOut | 'new' | null>(null);
  const [deleting, setDeleting] = useState<RuleOut | null>(null);

  // Any change to the rules re-runs categorization on the server.
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: listRulesQueryKey() });
    invalidateUserLayer(queryClient);
  };
  const onError = (error: unknown) => toast.error(errorMessage(error));
  const toggle = useMutation({ ...updateRuleMutation(), onSuccess: refresh, onError });
  const reorder = useMutation({ ...reorderRulesMutation(), onSuccess: refresh, onError });
  const remove = useMutation({
    ...deleteRuleMutation(),
    onSuccess: () => {
      setDeleting(null);
      refresh();
    },
    onError,
  });
  const run = useMutation({
    ...runRulesMutation(),
    onSuccess: (result) => {
      refresh();
      toast.success(
        `Checked ${result.processed} transactions: ${result.categorized} now have a category.`,
      );
    },
    onError,
  });

  const names: Names = {
    accounts: accounts.names,
    categories: categoryNames(categories.data),
    merchants: new Map(merchants.data?.map((merchant) => [merchant.id, merchant.name])),
  };
  const move = (index: number, by: -1 | 1) => {
    const ids = (rules.data ?? []).map((rule) => rule.id);
    const [current, other] = [ids[index], ids[index + by]];
    if (!current || !other) return;
    ids[index] = other;
    ids[index + by] = current;
    reorder.mutate({ body: { ids } });
  };

  return (
    <>
      <PageHeader
        title="Rules"
        actions={
          <>
            <Button variant="outline" disabled={run.isPending} onClick={() => run.mutate({})}>
              <Play aria-hidden />
              Run rules now
            </Button>
            <Button onClick={() => setEditing('new')}>
              <Plus aria-hidden />
              New rule
            </Button>
          </>
        }
      />
      {rules.isPending && <Skeleton className="h-48 w-full max-w-4xl" />}
      {rules.isError && (
        <Alert variant="destructive">
          <AlertTitle>Couldn't load rules</AlertTitle>
          <AlertDescription>{errorMessage(rules.error)}</AlertDescription>
        </Alert>
      )}
      {rules.data?.length === 0 && (
        <Card className="max-w-xl">
          <CardHeader>
            <CardTitle>No rules yet</CardTitle>
            <CardDescription>
              A rule says "when a transaction looks like this, give it that category".
            </CardDescription>
          </CardHeader>
        </Card>
      )}
      <ol className="max-w-4xl space-y-2">
        {rules.data?.map((rule, index) => (
          <li key={rule.id} className="flex items-start gap-3 rounded-lg border p-3">
            <Switch
              size="sm"
              className="mt-1"
              aria-label={`Enable ${rule.name}`}
              checked={rule.enabled}
              disabled={toggle.isPending}
              onCheckedChange={(enabled) =>
                toggle.mutate({
                  path: { rule_id: rule.id },
                  body: ruleToInput(rule, { enabled }),
                })
              }
            />
            <div className="min-w-0 flex-1 space-y-0.5">
              <div className={rule.enabled ? 'font-medium' : 'font-medium text-muted-foreground'}>
                {rule.name}
                {!rule.enabled && (
                  <Badge variant="outline" className="ml-2">
                    Off
                  </Badge>
                )}
                {rule.stop_processing && (
                  <Badge variant="secondary" className="ml-2">
                    Stops here
                  </Badge>
                )}
              </div>
              <p className="text-sm text-muted-foreground">
                When {rule.match === 'any' ? 'any' : 'all'} of:{' '}
                {rule.conditions.map((condition) => describeCondition(condition, names)).join('; ')}
                {' → '}
                {rule.actions.map((action) => describeAction(action, names)).join(', ')}
              </p>
            </div>
            <div className="flex shrink-0 gap-0.5">
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={`Move ${rule.name} up`}
                disabled={index === 0 || reorder.isPending}
                onClick={() => move(index, -1)}
              >
                <ArrowUp aria-hidden />
              </Button>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={`Move ${rule.name} down`}
                disabled={index === (rules.data?.length ?? 0) - 1 || reorder.isPending}
                onClick={() => move(index, 1)}
              >
                <ArrowDown aria-hidden />
              </Button>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={`Edit ${rule.name}`}
                onClick={() => setEditing(rule)}
              >
                <Pencil aria-hidden />
              </Button>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={`Delete ${rule.name}`}
                onClick={() => setDeleting(rule)}
              >
                <Trash2 aria-hidden />
              </Button>
            </div>
          </li>
        ))}
      </ol>

      {editing && (
        <RuleEditor rule={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />
      )}
      <Dialog open={deleting !== null} onOpenChange={(open) => !open && setDeleting(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Delete “{deleting?.name}”?</DialogTitle>
            <DialogDescription>
              What it categorized goes back to the merchant's default, or to uncategorized. What you
              set by hand stays.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleting(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={remove.isPending}
              onClick={() => deleting && remove.mutate({ path: { rule_id: deleting.id } })}
            >
              Delete rule
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
