import { createRouter, createWebHashHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/library' },
  { path: '/library', component: () => import('../views/LibraryView.vue') },
  { path: '/import', component: () => import('../views/ImportWizard.vue') },
  { path: '/learn/:id', component: () => import('../views/LearnView.vue') },
  { path: '/shadow/:id', component: () => import('../views/ShadowView.vue') },
  { path: '/review/:id', component: () => import('../views/ReviewView.vue') },
  { path: '/quiz/:id', component: () => import('../views/QuizView.vue') },
  { path: '/review-session', component: () => import('../views/ReviewSessionView.vue') },
  { path: '/vocab-book', component: () => import('../views/VocabBookView.vue') },
  { path: '/settings', component: () => import('../views/SettingsView.vue') },
]

export default createRouter({
  history: createWebHashHistory(),
  routes,
})
