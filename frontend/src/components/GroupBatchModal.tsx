import { useState } from 'react';
import { Package } from 'lucide-react';
import { Button } from './Button';

export interface GroupBatchModalProps {
  itemCount: number;
  defaultName: string;
  isSaving: boolean;
  onSave: (name: string) => void;
  onClose: () => void;
  t: (key: string, options?: Record<string, unknown>) => string;
}

export function GroupBatchModal({
  itemCount,
  defaultName,
  isSaving,
  onSave,
  onClose,
  t,
}: GroupBatchModalProps) {
  const [name, setName] = useState(defaultName);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded-xl p-6 w-full max-w-md">
        <h3 className="text-lg font-semibold text-white mb-2 flex items-center gap-2">
          <Package className="w-5 h-5 text-cyan-700 dark:text-cyan-300" />
          {t('queue.batch.groupAsBatch')}
        </h3>
        <p className="text-sm text-bambu-gray mb-4">
          {t('queue.batch.groupAsBatchDescription', { count: itemCount })}
        </p>
        <label className="block text-sm font-medium text-white mb-2">
          {t('queue.batch.nameLabel')}
        </label>
        <input
          type="text"
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t('queue.batch.namePlaceholder')}
          maxLength={120}
          className="w-full px-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white focus:border-bambu-green focus:outline-none mb-5"
        />
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={isSaving}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => {
              const trimmed = name.trim();
              if (trimmed) onSave(trimmed);
            }}
            disabled={isSaving || !name.trim()}
          >
            {isSaving ? t('common.saving') : t('queue.batch.create')}
          </Button>
        </div>
      </div>
    </div>
  );
}
