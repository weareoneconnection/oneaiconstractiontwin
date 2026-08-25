import { cp, mkdir } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
const here=dirname(fileURLToPath(import.meta.url));
const root=join(here,"..");
const src=join(root,"node_modules","cesium","Build","Cesium");
const dst=join(root,"public","cesium");
await mkdir(dst,{recursive:true});
for(const name of ["Workers","ThirdParty","Assets","Widgets"]){
  await cp(join(src,name),join(dst,name),{recursive:true,force:true});
}
console.log("Cesium runtime assets copied to public/cesium");
