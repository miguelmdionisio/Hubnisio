import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Archive, ArchiveRestore, FolderInput, Pencil, Plus, Trash2 } from 'lucide-react';
import { type FormEvent, type ReactNode, useState } from 'react';
import { toast } from 'sonner';
import {
  createCategoryMutation,
  deleteCategoryMutation,
  updateCategoryMutation,
} from '@/api/@tanstack/react-query.gen';
import type { CategoryGroupOut, CategoryKind, CategoryOut } from '@/api/types.gen';
import { PageHeader } from '@/components/app-shell';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardAction, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Switch } from '@/components/ui/switch';
import { errorMessage } from '@/lib/errors';
import { useCategories } from './category-picker';
import { invalidateUserLayer } from './use-transaction-edits';

type Editing =
  | { type: 'new-group' }
  | { type: 'new-category'; group: CategoryGroupOut }
  | { type: 'rename'; category: CategoryOut }
  | { type: 'move'; category: CategoryOut; from: CategoryGroupOut };

function useCategoryEdits(onDone: () => void) {
  const queryClient = useQueryClient();
  const options = {
    onSuccess: () => {
      invalidateUserLayer(queryClient);
      onDone();
    },
    // 409 when a category is still in use: the API says what to do instead.
    onError: (error: unknown) => toast.error(errorMessage(error)),
  };
  return {
    create: useMutation({ ...createCategoryMutation(), ...options }),
    update: useMutation({ ...updateCategoryMutation(), ...options }),
    remove: useMutation({ ...deleteCategoryMutation(), ...options }),
  };
}

export function CategoriesPage() {
  const categories = useCategories();
  const [showArchived, setShowArchived] = useState(false);
  const [dialog, setDialog] = useState<Editing | null>(null);
  const edits = useCategoryEdits(() => setDialog(null));

  const groups = (categories.data ?? [])
    .filter((group) => showArchived || !group.archived)
    .map((group) => ({
      ...group,
      children: group.children.filter((child) => showArchived || !child.archived),
    }));
  const archive = (category: CategoryOut, archived: boolean) =>
    edits.update.mutate({ path: { category_id: category.id }, body: { archived } });
  const remove = (category: CategoryOut) =>
    edits.remove.mutate({ path: { category_id: category.id } });

  return (
    <>
      <PageHeader
        title="Categories"
        description="Groups hold categories; transactions can go in either. Archiving hides a category from pickers without losing what's in it."
        actions={
          <>
            <Label className="gap-2 font-normal">
              <Switch checked={showArchived} onCheckedChange={setShowArchived} size="sm" />
              Show archived
            </Label>
            <Button onClick={() => setDialog({ type: 'new-group' })}>
              <Plus aria-hidden />
              New group
            </Button>
          </>
        }
      />
      {categories.isPending && <Skeleton className="h-64 w-full max-w-3xl" />}
      {categories.isError && (
        <Alert variant="destructive">
          <AlertTitle>Couldn't load categories</AlertTitle>
          <AlertDescription>{errorMessage(categories.error)}</AlertDescription>
        </Alert>
      )}
      <div className="grid max-w-3xl gap-4">
        {groups.map((group) => {
          const total = group.transactions + group.children.reduce((n, c) => n + c.transactions, 0);
          return (
            <Card key={group.id} size="sm" className={group.archived ? 'opacity-70' : undefined}>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  {group.name}
                  {group.kind === 'income' && <Badge variant="secondary">Income</Badge>}
                  {group.archived && <Badge variant="outline">Archived</Badge>}
                  <span className="text-xs font-normal text-muted-foreground">
                    {total} {total === 1 ? 'transaction' : 'transactions'}
                  </span>
                </CardTitle>
                <CardAction className="flex gap-1">
                  {!group.archived && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setDialog({ type: 'new-category', group })}
                    >
                      <Plus aria-hidden />
                      Add category
                    </Button>
                  )}
                  <RowActions
                    name={group.name}
                    archived={group.archived}
                    onRename={() => setDialog({ type: 'rename', category: group })}
                    onArchive={(archived) => archive(group, archived)}
                    onDelete={() => remove(group)}
                  />
                </CardAction>
              </CardHeader>
              {group.children.length > 0 && (
                <CardContent>
                  <ul className="divide-y">
                    {group.children.map((category) => (
                      <li
                        key={category.id}
                        className="flex items-center justify-between gap-2 py-1.5 pl-3 text-sm"
                      >
                        <span className={category.archived ? 'text-muted-foreground' : undefined}>
                          {category.name}
                          {category.archived && (
                            <Badge variant="outline" className="ml-2">
                              Archived
                            </Badge>
                          )}
                          <span className="ml-2 text-xs text-muted-foreground">
                            {category.transactions}
                          </span>
                        </span>
                        <RowActions
                          name={category.name}
                          archived={category.archived}
                          onRename={() => setDialog({ type: 'rename', category })}
                          onMove={() => setDialog({ type: 'move', category, from: group })}
                          onArchive={(archived) => archive(category, archived)}
                          onDelete={() => remove(category)}
                        />
                      </li>
                    ))}
                  </ul>
                </CardContent>
              )}
            </Card>
          );
        })}
      </div>

      {dialog?.type === 'new-group' && (
        <NameDialog
          title="New group"
          label="Group name"
          submitLabel="Create group"
          withKind
          pending={edits.create.isPending}
          onClose={() => setDialog(null)}
          onSubmit={(name, kind) => edits.create.mutate({ body: { name, kind } })}
        />
      )}
      {dialog?.type === 'new-category' && (
        <NameDialog
          title={`New category in ${dialog.group.name}`}
          label="Category name"
          submitLabel="Create category"
          pending={edits.create.isPending}
          onClose={() => setDialog(null)}
          onSubmit={(name) => edits.create.mutate({ body: { name, parent_id: dialog.group.id } })}
        />
      )}
      {dialog?.type === 'rename' && (
        <NameDialog
          title={`Rename ${dialog.category.name}`}
          label="Name"
          submitLabel="Rename"
          initial={dialog.category.name}
          pending={edits.update.isPending}
          onClose={() => setDialog(null)}
          onSubmit={(name) =>
            edits.update.mutate({ path: { category_id: dialog.category.id }, body: { name } })
          }
        />
      )}
      {dialog?.type === 'move' && (
        <MoveDialog
          category={dialog.category}
          groups={(categories.data ?? []).filter(
            (group) => !group.archived && group.id !== dialog.from.id,
          )}
          pending={edits.update.isPending}
          onClose={() => setDialog(null)}
          onMove={(groupId) =>
            edits.update.mutate({
              path: { category_id: dialog.category.id },
              body: { parent_id: groupId },
            })
          }
        />
      )}
    </>
  );
}

function RowActions({
  name,
  archived,
  onRename,
  onMove,
  onArchive,
  onDelete,
}: {
  name: string;
  archived: boolean;
  onRename: () => void;
  onMove?: () => void;
  onArchive: (archived: boolean) => void;
  onDelete: () => void;
}) {
  return (
    <div className="flex shrink-0 gap-0.5">
      <IconAction label={`Rename ${name}`} onClick={onRename}>
        <Pencil aria-hidden />
      </IconAction>
      {onMove && (
        <IconAction label={`Move ${name}`} onClick={onMove}>
          <FolderInput aria-hidden />
        </IconAction>
      )}
      <IconAction
        label={`${archived ? 'Unarchive' : 'Archive'} ${name}`}
        onClick={() => onArchive(!archived)}
      >
        {archived ? <ArchiveRestore aria-hidden /> : <Archive aria-hidden />}
      </IconAction>
      <IconAction label={`Delete ${name}`} onClick={onDelete}>
        <Trash2 aria-hidden />
      </IconAction>
    </div>
  );
}

function IconAction({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <Button variant="ghost" size="icon-sm" aria-label={label} title={label} onClick={onClick}>
      {children}
    </Button>
  );
}

function NameDialog({
  title,
  label,
  submitLabel,
  initial = '',
  withKind,
  pending,
  onClose,
  onSubmit,
}: {
  title: string;
  label: string;
  submitLabel: string;
  initial?: string;
  withKind?: boolean;
  pending: boolean;
  onClose: () => void;
  onSubmit: (name: string, kind: CategoryKind) => void;
}) {
  const [name, setName] = useState(initial);
  const [kind, setKind] = useState<CategoryKind>('expense');
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (name.trim()) onSubmit(name.trim(), kind);
  };

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-sm">
        <form onSubmit={submit} className="space-y-4">
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription className="sr-only">{label}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="category-name">{label}</Label>
            <Input
              id="category-name"
              value={name}
              maxLength={80}
              autoFocus
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          {withKind && (
            <div className="space-y-2">
              <Label htmlFor="category-kind">Holds</Label>
              <Select value={kind} onValueChange={(value) => setKind(value as CategoryKind)}>
                <SelectTrigger id="category-kind" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="expense">Spending</SelectItem>
                  <SelectItem value="income">Income</SelectItem>
                </SelectContent>
              </Select>
            </div>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={pending || !name.trim()}>
              {submitLabel}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function MoveDialog({
  category,
  groups,
  pending,
  onClose,
  onMove,
}: {
  category: CategoryOut;
  groups: CategoryGroupOut[];
  pending: boolean;
  onClose: () => void;
  onMove: (groupId: string) => void;
}) {
  const [groupId, setGroupId] = useState('');
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Move {category.name}</DialogTitle>
          <DialogDescription>
            It takes its transactions along, and becomes spending or income like the new group.
          </DialogDescription>
        </DialogHeader>
        <Select value={groupId} onValueChange={setGroupId}>
          <SelectTrigger aria-label="New group" className="w-full">
            <SelectValue placeholder="Choose a group" />
          </SelectTrigger>
          <SelectContent>
            {groups.map((group) => (
              <SelectItem key={group.id} value={group.id}>
                {group.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={pending || !groupId} onClick={() => onMove(groupId)}>
            Move
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
