import React from 'react';
import { Users, Info } from 'lucide-react';
import { runtimeConfig } from '../config/runtime';

export default function IdentityManager() {
  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight text-slate-900 dark:text-white">Identity & Users</h1>
      </div>
      
      <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 shadow-sm p-8 rounded-xl flex flex-col items-center justify-center text-center max-w-2xl mx-auto mt-12">
        <div className="w-16 h-16 bg-blue-500/10 text-[var(--color-blue-500)] rounded-full flex items-center justify-center mb-6">
          <Users className="w-8 h-8" />
        </div>
        <h2 className="text-xl font-bold text-slate-900 dark:text-white mb-4">Keycloak Integration Required</h2>
        <p className="text-slate-600 dark:text-slate-400 mb-6">
          Keycloak remains the source of truth for human identity and platform-wide roles. Open Talon now stores organization membership and organization roles in Postgres, so Keycloak is still where you create users, reset passwords, and assign platform-global <code>admin</code> access, while organization ownership and membership are managed inside Open Talon.
        </p>
        <a 
          href={runtimeConfig.keycloakBaseUrl}
          target="_blank" 
          rel="noopener noreferrer"
          className="bg-blue-500 hover:bg-sky-600 text-white font-medium py-2 px-6 rounded transition-colors inline-flex items-center"
        >
          Open Keycloak Admin Console
          <Info className="w-4 h-4 ml-2" />
        </a>
      </div>
    </div>
  );
}
