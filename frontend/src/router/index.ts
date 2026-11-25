import { createRouter, createWebHistory } from 'vue-router'

import Overview from '@/views/Overview.vue'
import WorkbenchView from '@/views/WorkbenchView.vue'
import FetchConsoleView from '@/views/FetchConsoleView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: Overview },
    { path: '/fetch_console', name: 'fetch_console', component: FetchConsoleView },
    { path: '/:moduleKey', name: 'module', component: WorkbenchView, props: true },
  ],
})

export default router
