<script lang="ts">
  let {
    size = "md",
    color = "primary",
  }: {
    size?: "sm" | "md" | "lg";
    color?: "primary" | "foreground";
  } = $props();

  const sizes = {
    sm: "h-4 w-4",
    md: "h-8 w-8",
    lg: "h-10 w-10",
  };

  const colors = {
    primary: "border-primary",
    foreground: "border-foreground",
  };
</script>

<div
  class="animate-spin rounded-full border-2 border-t-transparent {sizes[size]} {colors[color]}"
></div>
