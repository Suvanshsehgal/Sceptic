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
  const [currentTab, setCurrentTab] = useState<'dashboard' | 'projects' | 'audits' | 'features' | 'findings' | 'docs'>('dashboard');
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
          title: 'Verification Dashboard',
          subtitle: 'Real-time overview of code verification metrics and trust scores',
        };
      case 'projects':
        return {
          title: 'Project Repositories',
          subtitle: 'Managed projects synchronized between Web and Sceptic CLI',
        };
      case 'audits':
        return {
          title: 'Audit Runs Repository',
          subtitle: 'Detailed history of pull request and CLI code audits',
        };
      case 'features':
        return {
          title: 'Feature Architecture Scoping',
          subtitle: 'Feasibility, complexity, and risk analysis for proposed features',
        };
      case 'findings':
        return {
          title: 'All Verification Findings',
          subtitle: 'Aggregated security flaws, spec violations, and hallucinated APIs',
        };
      case 'docs':
        return {
          title: 'Documentation Center',
          subtitle: 'Architecture guide, CLI installation, and verification specifications',
        };
      default:
        return { title: 'Sceptic', subtitle: '' };
    }
  };

  const headerInfo = getHeaderInfo();

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col antialiased">
      {/* Navigation Sidebar */}
      <Sidebar
        currentTab={currentTab}
        onSelectTab={handleTabChange}
        mobileOpen={mobileMenuOpen}
        onCloseMobile={() => setMobileMenuOpen(false)}
      />

      {/* Main Content Area */}
      <div className="lg:pl-64 flex flex-col flex-1 min-h-screen">
        <Header
          onOpenMobile={() => setMobileMenuOpen(true)}
          title={headerInfo.title}
          subtitle={headerInfo.subtitle}
        />

        <main className="flex-1 p-4 sm:p-6 lg:p-8 max-w-7xl w-full mx-auto">
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