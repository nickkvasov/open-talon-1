import React from 'react';
import { LogOut, User, Moon, Sun } from 'lucide-react';
import { useTheme } from '../../providers/ThemeProvider';

export default function Header({ user, signOut }) {
  const { isDarkMode, toggleTheme } = useTheme();
  
  return (
    <header className="h-16 bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between px-6 z-10 transition-colors">
      <div className="flex items-center">
        {/* Placeholder for Breadcrumb */}
      </div>
      
      <div className="flex items-center space-x-4">
        <button 
          onClick={toggleTheme}
          className="p-2 rounded-full hover:bg-slate-100 dark:hover:bg-slate-800/50 text-slate-500 dark:text-slate-400 transition-colors"
          title="Toggle Theme"
        >
          {isDarkMode ? <Sun className="w-5 h-5" /> : <Moon className="w-5 h-5" />}
        </button>

        <div className="flex items-center space-x-2 pl-4 border-l border-slate-200 dark:border-slate-700">
          <div className="w-8 h-8 rounded-full bg-slate-200 dark:bg-slate-700 flex items-center justify-center text-slate-600 dark:text-slate-300">
            <User className="w-4 h-4" />
          </div>
          <span className="text-sm font-medium text-slate-700 dark:text-slate-300 hidden md:block">
            {user?.profile?.name || user?.profile?.preferred_username || 'Admin User'}
          </span>
          <button 
            onClick={signOut}
            className="ml-2 p-1.5 text-slate-400 hover:text-red-500 transition-colors"
            title="Sign Out"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </div>
    </header>
  );
}
