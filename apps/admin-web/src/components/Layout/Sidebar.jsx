import React from 'react';
import { NavLink } from 'react-router-dom';
import { LayoutDashboard, Users, Bot, FolderKanban, KeySquare, Server, Building2 } from 'lucide-react';

const navItems = [
  { path: '/dashboard', label: 'Overview', icon: LayoutDashboard },
  { path: '/identity', label: 'Identity & Users', icon: Users },
  { path: '/organizations', label: 'Organizations', icon: Building2 },
  { path: '/swarm', label: 'Swarm Resources', icon: Bot },
  { path: '/workspaces', label: 'Workspaces', icon: FolderKanban },
  { path: '/providers', label: 'Providers', icon: Server },
  { path: '/api-keys', label: 'API Keys', icon: KeySquare },
];

export default function Sidebar() {
  return (
    <div className="w-64 bg-white dark:bg-slate-900 border-r border-slate-200 dark:border-slate-800 flex flex-col z-20">
      <div className="h-16 flex items-center px-6 font-bold text-xl tracking-tight text-slate-800 dark:text-white border-b border-white/10">
        Open Talon
      </div>
      <div className="flex-1 overflow-y-auto py-4">
        <nav className="space-y-1 px-3">
          {navItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              className={({ isActive }) =>
                `flex items-center px-3 py-2.5 rounded-lg transition-all duration-200 ${
                  isActive 
                    ? 'bg-blue-500/10 text-[var(--color-blue-500)] font-medium' 
                    : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800/50 dark:hover:text-slate-200'
                }`
              }
            >
              <item.icon className="w-5 h-5 mr-3" />
              {item.label}
            </NavLink>
          ))}
        </nav>
      </div>
    </div>
  );
}
