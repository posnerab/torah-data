# 🚀 Quick Deployment Checklist

## ✅ Prerequisites (Already Done)
- [x] All R packages installed (`requirements.R`)
- [x] rsconnect package installed (`install_rsconnect.R`)
- [x] App files ready (`app.R`, `Data.xlsx`)

## 🔑 Next Steps

### 1. Get Shinyapps.io Credentials
1. Go to [shinyapps.io](https://www.shinyapps.io/) and sign up/login
2. Go to **Account** → **Tokens**
3. Copy your:
   - **Account name**
   - **Token** 
   - **Secret**

### 2. Configure Your Account
```r
rsconnect::setAccountInfo(
  name='YOUR_ACCOUNT_NAME',
  token='YOUR_TOKEN', 
  secret='YOUR_SECRET'
)
```

### 3. Deploy Your App
```r
rsconnect::deployApp(
  appName = "torah-data-explorer",
  appTitle = "Torah Data Explorer",
  appFiles = c("app.R", "Data.xlsx"),
  forceUpdate = TRUE
)
```

### 4. Access Your App
Your app will be available at:
```
https://YOUR_ACCOUNT_NAME.shinyapps.io/torah-data-explorer/
```

## 📊 What You'll Get

Your deployed app will include:
- **8 Data Sheets**: Fasts, Haftaros, Hebcal, Holidays, Parasha-Mitzvos, Parashiyos, Pasukim, Zmanim
- **Interactive Tables**: Sort, filter, search your data
- **Dynamic Charts**: Bar, Line, Scatter, Histogram, Box Plot
- **Boolean Filtering**: Checkbox filters for true/false columns
- **Professional UI**: Clean Shiny Dashboard interface

## ⚠️ Important Notes

- **File Size**: Your Data.xlsx is 7MB, so deployment may take 5-10 minutes
- **Free Limits**: 25 hours/month, 1GB RAM, 1GB storage
- **Updates**: Use `rsconnect::deployApp(forceUpdate = TRUE)` to update

## 🆘 Need Help?

- Check `DEPLOYMENT_GUIDE.md` for detailed instructions
- Run `deploy.R` for guided deployment
- Visit [docs.shinyapps.io](https://docs.shinyapps.io/) for official docs 