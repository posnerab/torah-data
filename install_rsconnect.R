# Install rsconnect package for Shinyapps.io deployment
options(repos = c(CRAN = "https://cran.rstudio.com/"))

if (!require(rsconnect)) {
  install.packages("rsconnect")
  cat("rsconnect package installed successfully!\n")
} else {
  cat("rsconnect package already installed.\n")
}

library(rsconnect)
cat("rsconnect package loaded successfully!\n")
cat("\nNext steps:\n")
cat("1. Get your Shinyapps.io credentials\n")
cat("2. Run: rsconnect::setAccountInfo(name='YOUR_ACCOUNT', token='YOUR_TOKEN', secret='YOUR_SECRET')\n")
cat("3. Run: rsconnect::deployApp()\n") 