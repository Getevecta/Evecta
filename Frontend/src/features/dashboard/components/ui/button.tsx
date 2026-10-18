import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "./utils";

/**
 * Dashboard uses exactly two visual button types:
 * - primary (default): .evecta-primary-btn
 * - secondary (outline | secondary): .evecta-secondary-btn
 */
const buttonVariants = cva(
  "inline-flex items-center justify-center whitespace-nowrap font-medium transition-none disabled:pointer-events-none disabled:opacity-50 outline-none focus-visible:outline-none [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default:
          "border border-transparent bg-[#9164FF] text-white evecta-primary-btn",
        primary:
          "border border-transparent bg-[#9164FF] text-white evecta-primary-btn",
        outline:
          "border border-transparent bg-background text-[#030011] evecta-secondary-btn",
        secondary:
          "border border-transparent bg-background text-[#030011] evecta-secondary-btn",
      },
      size: {
        default: "",
        sm: "",
        lg: "",
        icon: "",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

const Button = React.forwardRef<
  HTMLButtonElement,
  React.ComponentProps<"button"> &
    VariantProps<typeof buttonVariants> & {
      asChild?: boolean;
    }
>(({ className, variant, size, asChild = false, ...props }, ref) => {
  const Comp = asChild ? Slot : "button";

  return (
    <Comp
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      ref={ref}
      {...props}
    />
  );
});
Button.displayName = "Button";

export { Button, buttonVariants };
