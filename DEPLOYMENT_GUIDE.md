# Deploying Torah Data Explorer to Shinyapps.io

This guide will walk you through deploying your R Shiny app to Shinyapps.io.

## Prerequisites

1. **Shinyapps.io Account**: Sign up at [shinyapps.io](https://www.shinyapps.io/)
2. **R and RStudio**: Make sure you have R installed
3. **All Required Packages**: Run `requirements.R` first

## Step 1: Install rsconnect Package

```r
install.packages("rsconnect")
```

## Step 2: Get Your Shinyapps.io Credentials

1. Log in to [shinyapps.io](https://www.shinyapps.io/)
2. Go to your **Account** page
3. Click on **Tokens** tab
4. Click **Show** to reveal your token and secret
5. Copy your **Account name**, **Token**, and **Secret**

## Step 3: Configure Your Account

Run this command in R, replacing the placeholders with your actual credentials:

```r
rsconnect::setAccountInfo(
  name='YOUR_ACCOUNT_NAME',
  token='YOUR_TOKEN',
  secret='YOUR_SECRET'
)
```

## Step 4: Deploy the App

### Option A: Use the Deployment Script
```r
source("deploy.R")
```

### Option B: Manual Deployment
```r
library(rsconnect)
rsconnect::deployApp(
  appName = "torah-data-explorer",
  appTitle = "Torah Data Explorer",
  appFiles = c("app.R", "Data.xlsx"),
  forceUpdate = TRUE
)
```

## Step 5: Access Your App

After successful deployment, your app will be available at:
```
https://YOUR_ACCOUNT_NAME.shinyapps.io/torah-data-explorer/
```

## Troubleshooting

### Common Issues

1. **"Package not found" errors**:
   - Make sure all packages are installed locally
   - Run `requirements.R` again

2. **"File not found" errors**:
   - Ensure `Data.xlsx` is in the same directory as `app.R`
   - Check file permissions

3. **Deployment timeout**:
   - Your Excel file is large (7MB), so deployment may take several minutes
   - Be patient and don't interrupt the process

4. **Memory limits**:
   - Shinyapps.io has memory limits for free accounts
   - Consider upgrading if you hit limits

### Performance Optimization

For large datasets like yours (7MB Excel file):

1. **Consider data preprocessing**:
   - Convert Excel to CSV for faster loading
   - Remove unnecessary columns
   - Sample data for testing

2. **Optimize the app**:
   - Add loading indicators
   - Implement data caching
   - Use reactive expressions efficiently

## File Structure for Deployment

Your deployment directory should contain:
```
torah-data/
├── app.R                 # Main Shiny application
├── Data.xlsx            # Your data file
├── deploy.R             # Deployment script (optional)
└── requirements.R       # Package installation (for reference)
```

## Post-Deployment

1. **Test your app** thoroughly on Shinyapps.io
2. **Monitor usage** through your Shinyapps.io dashboard
3. **Update as needed** using the same deployment commands

## Free Account Limits

- **5 active applications**
- **25 hours of activity per month**
- **1GB of RAM per application**
- **1GB of storage**

## Updating Your App

To update your deployed app:

```r
rsconnect::deployApp(forceUpdate = TRUE)
```

## Support

- **Shinyapps.io Documentation**: [docs.shinyapps.io](https://docs.shinyapps.io/)
- **RStudio Support**: [support.rstudio.com](https://support.rstudio.com/)
- **Shiny Documentation**: [shiny.rstudio.com](https://shiny.rstudio.com/) 