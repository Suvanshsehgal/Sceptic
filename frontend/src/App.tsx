import React, { useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Sidebar, Header } from './components/Layout';
import { DashboardOverview } from './components/DashboardOverview';
import { ProjectsPage } from './components/ProjectsPage';
import { AuditsPage } from './components/AuditsPage';
import { AuditDetailView } from './components/AuditDetailView';
import { FeaturesPage } from './components/FeaturesPage';
import { FindingsPage } from './components/FindingsPage';
import { DocsCenter } from './components/DocsCenter';
import { DeploymentsPage } from './components/DeploymentsPage';
import { AuthProvider } from './context/AuthContext';
import { ErrorBoundary } from './components/ErrorBoundary';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5000,
      retry: 1,
    },
  },
});

function AppContent() {
  const [currentTab, setCurrentTab] = useState<'dashboard' | 'projects' | 'audits' | 'features' | 'findings' | 'deployments' | 'docs'>('dashboard');
  const [selectedAuditId, setSelectedAuditId] = useState<number | string | null>(null);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const handleSelectAudit = (id: number | string) => {
    setSelectedAuditId(id);
    setCurrentTab('audits');
  };

  const handleTabChange = (tab: string) => {
    setCurrentTab(tab as any);
    if (tab !== 'audits') {
      setSelectedAuditId(null);
    }
  };

  const getHeaderInfo = () => {
    if (selectedAuditId !== null && currentTab === 'audits') {
      return {
        title: `Audit Details #${selectedAuditId}`,
        subtitle: 'Granular verification results, findings, and evidence trace',
      };
    }
    switch (currentTab) {
      case 'dashboard':
        return {
          title: 'Overview',
          subtitle: 'Recent verification runs and where they stand',
        };
      case 'projects':
        return {
          title: 'Projects',
          subtitle: 'Repositories shared between the dashboard and the CLI',
        };
      case 'audits':
        return {
          title: 'Audits',
          subtitle: 'Pull request and CLI verification runs',
        };
      case 'features':
        return {
          title: 'Feature analysis',
          subtitle: 'Feasibility, complexity, and risk for proposed changes',
        };
      case 'findings':
        return {
          title: 'Findings',
          subtitle: 'Security issues, spec violations, and unknown APIs across audits',
        };
      case 'deployments':
        return {
          title: 'Deployments',
          subtitle: 'Live health, drift, and rollbacks',
        };
      case 'docs':
        return {
          title: 'Documentation',
          subtitle: 'Architecture, CLI setup, and verification rules',
        };
      default:
        return { title: 'Sceptic', subtitle: '' };
    }
  };

  const headerInfo = getHeaderInfo();

  return (
    <div className="flex min-h-screen flex-col bg-canvas text-ink antialiased">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-60 focus:rounded-lg focus:bg-accent focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-accent-ink"
      >
        Skip to main content
      </a>
      {/* Navigation Sidebar */}
      <Sidebar
        currentTab={currentTab}
        onSelectTab={handleTabChange}
        mobileOpen={mobileMenuOpen}
        onCloseMobile={() => setMobileMenuOpen(false)}
      />

      {/* Main Content Area */}
      <div className="flex min-h-screen flex-1 flex-col lg:pl-64">
        <Header
          onOpenMobile={() => setMobileMenuOpen(true)}
          title={headerInfo.title}
          subtitle={headerInfo.subtitle}
        />

        <main id="main-content" tabIndex={-1} className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 focus:outline-none sm:px-6 lg:px-8 lg:py-8">
          {currentTab === 'dashboard' && (
            <DashboardOverview
              onSelectAudit={handleSelectAudit}
              onNavigateTab={handleTabChange}
            />
          )}

          {currentTab === 'projects' && <ProjectsPage />}

          {currentTab === 'audits' && (
            <>
              {selectedAuditId !== null ? (
                <AuditDetailView
                  auditId={selectedAuditId as any}
                  onBack={() => setSelectedAuditId(null)}
                />
              ) : (
                <AuditsPage onSelectAudit={handleSelectAudit as any} />
              )}
            </>
          )}

          {currentTab === 'features' && <FeaturesPage />}

          {currentTab === 'findings' && (
            <FindingsPage onSelectAudit={handleSelectAudit as any} />
          )}

          {currentTab === 'deployments' && <DeploymentsPage />}

          {currentTab === 'docs' && <DocsCenter />}
        </main>
      </div>
    </div>
  );
}

function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <AppContent />
        </AuthProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}

export default App;