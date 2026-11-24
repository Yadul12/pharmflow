import React from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { FilterProvider } from "./context/FilterContext";
import { CancellationRefunds } from "./pages/CancellationRefunds";
import { CohortAnalytics } from "./pages/CohortAnalytics";
import { CustomerFunnel } from "./pages/CustomerFunnel";
import { CustomerRetention } from "./pages/CustomerRetention";
import { CustomerSegmentation } from "./pages/CustomerSegmentation";
import { ExecutiveOverview } from "./pages/ExecutiveOverview";
import { ProductCategories } from "./pages/ProductCategories";
import { Reports } from "./pages/Reports";
import { SqlLab } from "./pages/SqlLab";
import { SubscriptionPerformance } from "./pages/SubscriptionPerformance";

export const App: React.FC = () => {
  return (
    <BrowserRouter>
      <FilterProvider>
        <Layout>
          <Routes>
            <Route path="/" element={<ExecutiveOverview />} />
            <Route path="/funnel" element={<CustomerFunnel />} />
            <Route path="/retention" element={<CustomerRetention />} />
            <Route path="/cohorts" element={<CohortAnalytics />} />
            <Route path="/segmentation" element={<CustomerSegmentation />} />
            <Route path="/subscriptions" element={<SubscriptionPerformance />} />
            <Route path="/categories" element={<ProductCategories />} />
            <Route path="/cancellations" element={<CancellationRefunds />} />
            <Route path="/sql-lab" element={<SqlLab />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Layout>
      </FilterProvider>
    </BrowserRouter>
  );
};

export default App;
