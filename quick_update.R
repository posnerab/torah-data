#!/usr/bin/env Rscript
# Quick Update Script for Torah Data Explorer
# Run this script to quickly update your deployed app

library(rsconnect)

# Configuration
APP_NAME <- "torah-data-explorer"
APP_FILES <- c("app.R", "Data.xlsx")

# Quick update function
quick_update <- function() {
  cat("🔄 Quick update starting...\n")
  
  # Check files exist
  for (file in APP_FILES) {
    if (!file.exists(file)) {
      cat("❌ Error: Missing file", file, "\n")
      quit(status = 1)
    }
  }
  
  # Deploy with minimal output
  tryCatch({
    cat("📤 Deploying...\n")
    rsconnect::deployApp(
      appName = APP_NAME,
      appFiles = APP_FILES,
      forceUpdate = TRUE,
      logLevel = "quiet"
    )
    cat("✅ Update complete!\n")
  }, error = function(e) {
    cat("❌ Update failed:", e$message, "\n")
    quit(status = 1)
  })
}

# Run quick update
quick_update() 