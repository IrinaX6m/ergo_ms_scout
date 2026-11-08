import '../styles/scout-workflow.scss'
import '../prototypes/inspector.scss'

const loadHome = () => import('../components/ScoutPage.vue')

export default {
  ScoutUX004: {
    path: '/scout/ux-004', component: () => import('../prototypes/ScoutUX004.vue'),
    meta: { titleKey: 'scout.routes.home', requiresAuth: true },
  },
  ScoutHome: {
    path: '/scout',
    component: loadHome,
    meta: {
      titleKey: 'scout.routes.home',
      requiresAuth: true,
    },
  },
}
