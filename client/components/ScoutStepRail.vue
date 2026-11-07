<script setup>
defineProps({
  steps: { type: Array, required: true },
  interactive: { type: Boolean, default: false },
})
defineEmits(['select'])
</script>

<template>
  <nav class="step-rail">
    <ol class="step-rail__list">
      <li
        v-for="step in steps"
        :key="step.id"
        class="step-rail__item"
        :class="`step-rail__item--${step.state}`"
      >
        <button
          type="button"
          class="step-rail__button"
          :disabled="!interactive || step.disabled"
          :aria-current="step.state === 'current' ? 'step' : undefined"
          @click="$emit('select', step.id)"
        >
          <span class="step-rail__marker" aria-hidden="true">{{
            step.state === 'passed' ? '✓' : step.marker
          }}</span>
          <span class="step-rail__label">{{ step.label }}</span>
        </button>
      </li>
    </ol>
  </nav>
</template>

<style scoped>
.step-rail__list {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  list-style: none;
  padding: 0;
  margin: 0;
}
.step-rail__item {
  position: relative;
  min-width: 0;
}
.step-rail__item:not(:last-child)::after {
  content: '';
  position: absolute;
  top: 1rem;
  inset-inline-start: calc(50% + 1rem);
  width: calc(100% - 2rem);
  height: 2px;
  background: var(--ui-border);
}
.step-rail__item--passed::after {
  background: var(--ui-accent);
}
.step-rail__button {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  width: 100%;
  padding: 0;
  border: 0;
  color: var(--ui-text);
  background: transparent;
  font: inherit;
  cursor: pointer;
}
.step-rail__button:disabled {
  cursor: default;
}
.step-rail__button:focus-visible {
  outline: 2px solid var(--ui-accent);
  outline-offset: 4px;
}
.step-rail__marker {
  display: grid;
  place-items: center;
  width: 2rem;
  height: 2rem;
  border: 2px solid var(--ui-border);
  border-radius: 50%;
  background: var(--ui-surface);
  color: var(--ui-text-muted);
}
.step-rail__item--current .step-rail__marker,
.step-rail__item--passed .step-rail__marker {
  border-color: var(--ui-accent);
  color: var(--ui-accent);
}
.step-rail__item--current .step-rail__label {
  font-weight: 600;
}
.step-rail__label {
  max-width: 100%;
  font-size: 0.75rem;
  text-align: center;
  overflow-wrap: anywhere;
}
.step-rail__item--upcoming .step-rail__label {
  color: var(--ui-text-muted);
}
</style>
