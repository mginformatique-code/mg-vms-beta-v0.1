import { useTheme } from "next-themes"
import { Toaster as Sonner, toast } from "sonner"

const Toaster = ({
  ...props
}) => {
  const { theme = "system" } = useTheme()

  return (
    <Sonner
      theme={theme}
      className="toaster group"
      closeButton
      toastOptions={{
        classNames: {
          toast:
            "group toast group-[.toaster]:bg-background group-[.toaster]:text-foreground group-[.toaster]:border-border group-[.toaster]:shadow-lg cursor-pointer",
          description: "group-[.toast]:text-muted-foreground",
          actionButton:
            "group-[.toast]:bg-primary group-[.toast]:text-primary-foreground",
          cancelButton:
            "group-[.toast]:bg-muted group-[.toast]:text-muted-foreground",
          closeButton:
            "group-[.toast]:bg-background group-[.toast]:border-border group-[.toast]:text-foreground",
        },
      }}
      {...props}
      onClick={(e) => {
        const el = e.target.closest("[data-sonner-toast]");
        if (el && !e.target.closest("[data-close-button]") && !e.target.closest("button")) {
          el.querySelector("[data-close-button]")?.click();
        }
        props.onClick?.(e);
      }} />
  );
}

export { Toaster, toast }
