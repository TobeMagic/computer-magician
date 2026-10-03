import fs from 'fs';
import path from 'path';

async function downloadImage(url: string, dest: string) {
  console.log(`Downloading ${url} -> ${dest}...`);
  const response = await fetch(url, {
    headers: {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
    }
  });
  if (!response.ok) {
    throw new Error(`Failed to fetch ${url}: ${response.statusText}`);
  }
  const arrayBuffer = await response.arrayBuffer();
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.writeFileSync(dest, Buffer.from(arrayBuffer));
  console.log(`✅ Success! Saved to ${dest} (Size: ${arrayBuffer.byteLength} bytes)`);
}

async function scrapeFromPages(pages: string[], dest: string) {
  for (const pageUrl of pages) {
    try {
      console.log(`Scraping page: ${pageUrl}...`);
      const response = await fetch(pageUrl, {
        headers: {
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
        }
      });
      if (!response.ok) {
        console.warn(`❌ Page fetch skipped: status ${response.status}`);
        continue;
      }
      const html = await response.text();
      
      // Match any upload.wikimedia.org thumbnail or original jpg url
      const matches = html.match(/https:\/\/upload\.wikimedia\.org\/wikipedia\/commons\/[^"' ]+\.jpg/g);
      if (!matches || matches.length === 0) {
        console.warn(`❌ No wikimedia image urls parsed on page ${pageUrl}`);
        continue;
      }

      // Filter for files that have 'Cypresses' or 'Wheatfield' or 'Wheat-Field' in their filename
      const filtered = Array.from(new Set(matches)).filter(url => {
        const lower = url.toLowerCase();
        return lower.includes('cypress') || lower.includes('wheatfield') || lower.includes('wheat_field');
      });

      if (filtered.length === 0) {
        console.warn(`❌ Found JPG matches but none about Cypresses/Wheatfield`);
        continue;
      }

      console.log(`Found ${filtered.length} relevant candidate links. Finding best rendering size...`);
      
      // Prioritize 1280px, then 1024px, then other thumbnails, then original
      const chosenUrl = filtered.find(url => url.includes('1280px')) 
                     || filtered.find(url => url.includes('1024px'))
                     || filtered.find(url => url.includes('/thumb/'))
                     || filtered[0];

      if (chosenUrl) {
         console.log(`🎉 Selected target image: ${chosenUrl}`);
         await downloadImage(chosenUrl, dest);
         return; // We have downloaded!
      }
    } catch (e: any) {
      console.warn(`❌ Error parsing ${pageUrl}: ${e.message}`);
    }
  }
  throw new Error(`Could not download wheat_field from any of the standard scraped pages.`);
}

async function main() {
  try {
    // Starry Night - Download static copy
    const starryUrl = "https://upload.wikimedia.org/wikipedia/commons/thumb/e/ea/Van_Gogh_-_Starry_Night_-_Google_Art_Project.jpg/1280px-Van_Gogh_-_Starry_Night_-_Google_Art_Project.jpg";
    await downloadImage(starryUrl, path.join(process.cwd(), 'public', 'starry_night.jpg'));

    // Try multiple source URLs that discuss the Wheat Field with Cypresses
    const candidatePages = [
      "https://en.wikipedia.org/wiki/A_Wheatfield_with_Cypresses",
      "https://en.wikipedia.org/wiki/Wheat_Field_with_Cypresses",
      "https://commons.wikimedia.org/wiki/File:Vincent_van_Gogh_-_A_Wheatfield_with_Cypresses_-_Google_Art_Project.jpg",
      "https://commons.wikimedia.org/wiki/File:Vincent_Willem_van_Gogh_-_A_Wheatfield_with_Cypresses_-_Google_Art_Project.jpg",
      "https://en.wikipedia.org/wiki/Fil:Vincent_van_Gogh_-_A_Wheatfield_with_Cypresses_-_Google_Art_Project.jpg"
    ];

    await scrapeFromPages(candidatePages, path.join(process.cwd(), 'public', 'wheat_field.jpg'));
    console.log("🚀 All asset compilations complete!");
  } catch (error: any) {
    console.error("Asset download failed:", error.message);
    
    // Safety fallback: if anything failed, let's copy starry_night to wheat_field so the UI never crashes
    try {
      const fallbackPath = path.join(process.cwd(), 'public', 'wheat_field.jpg');
      if (!fs.existsSync(fallbackPath) && fs.existsSync(path.join(process.cwd(), 'public', 'starry_night.jpg'))) {
        fs.copyFileSync(path.join(process.cwd(), 'public', 'starry_night.jpg'), fallbackPath);
        console.log("🚑 Created recovery copy of Starry Night for Wheat Field cypresses.");
      }
    } catch (_) {}
  }
}

main();
