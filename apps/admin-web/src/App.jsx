import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { useAuth } from 'react-oidc-context';
import Sidebar from './components/Layout/Sidebar';
import Header from './components/Layout/Header';

import Dashboard from './pages/Dashboard';

import IdentityManager from './pages/IdentityManager';
import Organizations from './pages/Organizations';
import SwarmResources from './pages/SwarmResources';
import Workspaces from './pages/Workspaces';
import Providers from './pages/Providers';
import ApiKeys from './pages/ApiKeys';

const App = () => {
  const auth = useAuth();

  if (auth.isLoading) {
    return <div className="min-h-screen flex items-center justify-center">Loading authentication...</div>;
  }

  if (auth.error) {
    return <div className="min-h-screen flex items-center justify-center text-red-500">Auth Error: {auth.error.message}</div>;
  }

  if (!auth.isAuthenticated) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-slate-50 dark:bg-slate-900">
        <div className="p-8 max-w-sm bg-white dark:bg-slate-800 shadow-xl rounded-xl text-center border border-slate-200 dark:border-slate-700">
          <h1 className="text-xl font-bold mb-4 text-slate-800 dark:text-white">Open Talon Administration</h1>
          <button 
            onClick={() => void auth.signinRedirect()} 
            className="w-full bg-blue-500 hover:bg-blue-600 text-white font-medium py-2 px-4 rounded transition-colors"
          >
            Sign in with Keycloak
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50 dark:bg-slate-900 transition-colors duration-200">
      <Sidebar />
      <div className="relative flex flex-col flex-1 overflow-y-auto overflow-x-hidden">
        <Header user={auth.user} signOut={() => void auth.signoutRedirect()} />
        <main>
          <Routes>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/identity" element={<IdentityManager />} />
            <Route path="/organizations" element={<Organizations />} />
            <Route path="/swarm" element={<SwarmResources />} />
            <Route path="/workspaces" element={<Workspaces />} />
            <Route path="/providers" element={<Providers />} />
            <Route path="/api-keys" element={<ApiKeys />} />
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </main>
      </div>
    </div>
  );
};

export default App;
