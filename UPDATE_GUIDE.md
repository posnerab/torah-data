# 🔄 App Update Guide

This guide explains how to update your deployed Torah Data Explorer app when you make changes.

## 📁 Update Scripts Available

### 1. **`update.sh`** (Recommended - Easiest)
```bash
./update.sh
```
- **What it does**: Quick command-line update
- **Best for**: Regular updates after making changes
- **Features**: 
  - Checks for required files
  - Minimal output
  - Fast execution

### 2. **`quick_update.R`** (R Script)
```bash
Rscript quick_update.R
```
- **What it does**: Quick R-based update
- **Best for**: When you prefer R commands
- **Features**:
  - Quiet deployment
  - Error handling
  - Exit codes for automation

### 3. **`update_app.R`** (Interactive)
```bash
Rscript update_app.R
```
- **What it does**: Interactive update with confirmation
- **Best for**: When you want to review before deploying
- **Features**:
  - File size information
  - User confirmation
  - Detailed progress
  - Troubleshooting tips

## 🚀 Quick Start

### After making changes to your app:

1. **Save your changes** to `app.R` or `Data.xlsx`
2. **Run the update**:
   ```bash
   ./update.sh
   ```
3. **Wait for completion** (usually 2-5 minutes)
4. **Your app is updated!** 🎉

## 📋 Update Workflow

### Typical Development Cycle:

1. **Make Changes**:
   - Edit `app.R` (add features, fix bugs)
   - Update `Data.xlsx` (add new data)
   - Test locally if needed

2. **Deploy Changes**:
   ```bash
   ./update.sh
   ```

3. **Verify Update**:
   - Visit your app URL
   - Test new features
   - Check that everything works

## ⚙️ Configuration

### Customizing App Name
If you want to change the app name, edit these files:
- `update.sh` - Line 15
- `quick_update.R` - Line 7
- `update_app.R` - Line 8

### Adding More Files
To include additional files in deployment, update the `APP_FILES` variable in the R scripts.

## 🔧 Troubleshooting

### Common Issues:

1. **"Rscript not found"**:
   - Install R from [r-project.org](https://www.r-project.org/)
   - Make sure R is in your PATH

2. **"Missing file" errors**:
   - Ensure `app.R` and `Data.xlsx` are in the same directory
   - Check file permissions

3. **"Account not configured"**:
   - Run: `rsconnect::setAccountInfo(name='YOUR_ACCOUNT', token='YOUR_TOKEN', secret='YOUR_SECRET')`

4. **Deployment timeout**:
   - Large files take longer to upload
   - Be patient and don't interrupt the process

### Performance Tips:

- **Small changes**: Use `./update.sh` for quick updates
- **Large changes**: Use `Rscript update_app.R` to see detailed progress
- **Automation**: Use `Rscript quick_update.R` in scripts

## 📊 Monitoring

### Check Deployment Status:
- Visit your Shinyapps.io dashboard
- Monitor app usage and performance
- Check for any error logs

### Update History:
- Each update replaces the previous version
- No version history is kept (upgrade to paid plan for this)
- Keep local backups of important changes

## 🎯 Best Practices

1. **Test Locally First**: Run your app locally before deploying
2. **Incremental Updates**: Make small changes and update frequently
3. **Backup Important Changes**: Keep local copies of significant modifications
4. **Monitor Usage**: Check your Shinyapps.io dashboard regularly
5. **Plan for Downtime**: Updates may cause brief app unavailability

## 🆘 Need Help?

- **Deployment Issues**: Check `DEPLOYMENT_GUIDE.md`
- **App Development**: Check `README_Shiny.md`
- **Shinyapps.io Support**: [docs.shinyapps.io](https://docs.shinyapps.io/) 