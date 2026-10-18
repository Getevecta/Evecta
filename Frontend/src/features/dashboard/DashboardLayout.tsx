import React from 'react';
import { Outlet } from 'react-router-dom';

/**
 * DashboardLayout - A clean layout for the dashboard
 * Removed extra wrapper div to prevent layout issues
 */
export default function DashboardLayout() {
  return <Outlet />;
}
