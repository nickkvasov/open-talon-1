import React from 'react';
import { AlertTriangle, X } from 'lucide-react';

export default function ConfirmationModal({ 
  isOpen, 
  onClose, 
  onConfirm, 
  title = 'Are you sure?', 
  message = 'This action cannot be undone.', 
  confirmText = 'Delete', 
  cancelText = 'Cancel',
  type = 'danger' 
}) {
  if (!isOpen) return null;

  const themes = {
    danger: {
      button: 'bg-rose-600 hover:bg-rose-700 shadow-rose-500/20',
      icon: 'bg-rose-100 dark:bg-rose-900/30 text-rose-600 dark:text-rose-400',
      border: 'border-rose-100 dark:border-rose-800'
    },
    warning: {
      button: 'bg-amber-600 hover:bg-amber-700 shadow-amber-500/20',
      icon: 'bg-amber-100 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400',
      border: 'border-amber-100 dark:border-amber-800'
    }
  };

  const theme = themes[type] || themes.danger;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm transition-opacity animate-in fade-in duration-200">
      <div className="bg-white dark:bg-slate-800 w-full max-w-md rounded-2xl shadow-2xl border border-slate-200 dark:border-slate-700 animate-in zoom-in-95 duration-200 overflow-hidden">
        <div className="p-6">
          <div className="flex items-start gap-4">
            <div className={`p-3 rounded-xl shrink-0 ${theme.icon}`}>
              <AlertTriangle className="w-6 h-6" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between mb-1">
                <h3 className="text-lg font-bold text-slate-900 dark:text-white truncate">
                  {title}
                </h3>
                <button 
                  onClick={onClose}
                  className="p-1 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
              <p className="text-sm text-slate-500 dark:text-slate-400 leading-relaxed">
                {message}
              </p>
            </div>
          </div>
        </div>
        
        <div className="bg-slate-50 dark:bg-slate-900/50 px-6 py-4 flex justify-end gap-3 border-t border-slate-100 dark:border-slate-700">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-sm font-semibold text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white transition-colors"
          >
            {cancelText}
          </button>
          <button
            type="button"
            onClick={() => { onConfirm(); onClose(); }}
            className={`px-6 py-2 text-sm font-bold text-white rounded-lg shadow-lg transition-all hover:scale-[1.02] active:scale-[0.98] ${theme.button}`}
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  );
}
