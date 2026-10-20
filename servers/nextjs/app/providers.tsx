'use client';

import { useEffect } from 'react';
import { Provider } from 'react-redux';
import { store } from '../store/store';
import ChatGptAuthRedirectHandler from './ChatGptAuthRedirectHandler';
import { initI18n } from '@/i18n';

export function Providers({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    initI18n();
  }, []);

  return <Provider store={store}>
      <ChatGptAuthRedirectHandler />
      {children}
  </Provider>;
}
