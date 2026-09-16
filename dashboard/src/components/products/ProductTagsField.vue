<template>
  <section class="product-tags-field">
    <div class="field-heading">
      <span>Tags</span>
      <button type="button" class="secondary-action" @click="inputVisible = true">+ Add Tag</button>
    </div>
    <input
      v-if="inputVisible"
      v-model.trim="draft"
      placeholder="Type a tag and press Enter"
      autocomplete="off"
      @keydown.enter.prevent="add"
      @blur="hideWhenEmpty"
    />
    <div class="product-tag-list">
      <span v-for="tag in tags" :key="tag" class="product-tag-pill dismissible">
        {{ tag }}
        <button type="button" :aria-label="`Remove ${tag} tag`" @click="remove(tag)">×</button>
      </span>
    </div>
    <span class="field-note">Product name and category are automatically added as tags. Add custom tags here.</span>
  </section>
</template>

<script setup>
/**
 * The tag list. Mutates the array it is given, the way PricingCard mutates `prices` — the parent's `form`
 * owns the data and this owns the half-typed tag, which is the only state the parent has no use for.
 */
import { ref } from "vue";
import { normalizeTag } from "../../stores/products";

const props = defineProps({ tags: { type: Array, required: true } });

const inputVisible = ref(false);
const draft = ref("");

function add() {
  const tag = normalizeTag(draft.value);
  if (tag && !props.tags.includes(tag)) props.tags.push(tag);
  draft.value = "";
}

function hideWhenEmpty() {
  if (!draft.value) inputVisible.value = false;
}

function remove(tag) {
  const index = props.tags.indexOf(tag);
  if (index >= 0) props.tags.splice(index, 1);
}
</script>
