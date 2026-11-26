const byId = (name) => document.getElementById(name);
let forecast;
let hostedMode = false;
let historyDays = 14;
const number = (value) => Number(value).toFixed(2);
const day = (value) => new Date(`${value}T12:00:00+05:30`).toLocaleDateString('en-IN', {day:'numeric',month:'short',timeZone:'Asia/Kolkata'});
const stamp = (value) => value ? new Date(value).toLocaleString('en-IN', {timeZone:'Asia/Kolkata',dateStyle:'medium',timeStyle:'short'}) + ' IST' : 'Not recorded in archive';
function chart() {
  const history = forecast.demand_history_mu.slice(-historyDays);
  const predicted = forecast.predictions;
  const components = byId('components').checked;
  const values = [...history, ...predicted.flatMap(row => components ? [row.ensemble_mu,row.chronos2_mu,row.tcn_mu] : [row.ensemble_mu])];
  const minimum = Math.floor((Math.min(...values)-5)/10)*10;
  const maximum = Math.ceil((Math.max(...values)+5)/10)*10;
  const width=1000, height=310, left=48, top=25, bottom=265;
  const count=history.length+7;
  const x = index => left+index*(width-left-22)/(count-1);
  const y = value => bottom-(value-minimum)/(maximum-minimum)*(bottom-top);
  const path = (series, start) => series.map((value,index) => `${index?'L':'M'}${x(start+index)},${y(value)}`).join(' ');
  const boundary = x(history.length-1);
  let svg = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Delhi daily electricity history and seven-day forecast in million units"><defs><linearGradient id="fill" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#8fb19c" stop-opacity=".22"/><stop offset="1" stop-color="#8fb19c" stop-opacity="0"/></linearGradient></defs><rect x="${boundary}" y="${top}" width="${width-boundary-20}" height="${bottom-top}" fill="#f6f8ee"/>`;
  for(let tick=0;tick<=4;tick++){const value=minimum+(maximum-minimum)*tick/4;svg+=`<line x1="${left}" y1="${y(value)}" x2="980" y2="${y(value)}" stroke="#edf1eb"/><text x="34" y="${y(value)+4}" text-anchor="end" fill="#8b978c" font-size="10">${value.toFixed(0)}</text>`;}
  svg+=`<text x="${boundary+12}" y="18" fill="#94a575" font-size="9" letter-spacing="1">FORECAST</text><line x1="${boundary}" y1="25" x2="${boundary}" y2="265" stroke="#cbd6b5" stroke-dasharray="4 4"/><path d="${path(history,0)} L${boundary},${bottom} L${left},${bottom} Z" fill="url(#fill)"/><path d="${path(history,0)}" fill="none" stroke="#346c58" stroke-width="2.5"/>`;
  if(components) for(const [key,color] of [['chronos2_mu','#8393bd'],['tcn_mu','#c79a71']]) svg+=`<path d="${path(predicted.map(row=>row[key]),history.length)}" fill="none" stroke="${color}" stroke-width="1.5" stroke-dasharray="4 3"/>`;
  svg+=`<path d="${path([history.at(-1),...predicted.map(row=>row.ensemble_mu)],history.length-1)}" fill="none" stroke="#99ad4e" stroke-width="2.5" stroke-dasharray="5 4"/>`;
  predicted.forEach((row,index)=>{svg+=`<circle cx="${x(history.length+index)}" cy="${y(row.ensemble_mu)}" r="4" fill="#99ad4e" stroke="white" stroke-width="2"><title>${day(row.date)}: ${number(row.ensemble_mu)} MU</title></circle>`;});
  for(let index=0;index<count;index++){if(index%Math.ceil(history.length/6)!==0&&index!==count-1&&index<history.length)continue;const date=new Date(`${forecast.forecast_origin}T12:00:00Z`);date.setUTCDate(date.getUTCDate()+index-history.length+1);svg+=`<text x="${x(index)}" y="291" text-anchor="middle" fill="#8b978c" font-size="9">${day(date.toISOString().slice(0,10))}</text>`;}
  byId('chart').innerHTML=svg+'</svg>';
}
function render(record){
  forecast=record;
  if(!record){byId('status').textContent='No saved forecast yet. Refresh to fetch Delhi observations and generate an outlook.';return;}
  byId('dashboard').hidden=false;
  const predictions=record.predictions;
  const latest=record.demand_history_mu.at(-1);
  const average=predictions.reduce((sum,row)=>sum+row.ensemble_mu,0)/7;
  const peak=predictions.reduce((best,row)=>row.ensemble_mu>best.ensemble_mu?row:best);
  for(const [name,value] of [['actual',latest],['average',average],['peak',peak.ensemble_mu]])byId(name).innerHTML=`${number(value)} <small>MU</small>`;
  byId('actual-date').textContent=`Reported for ${day(record.forecast_origin)}`;
  byId('change').textContent=latest ? `${((average/latest-1)*100).toFixed(1)}% vs latest observed day` : 'Seven-day ensemble mean';
  byId('peak-date').textContent=`${day(peak.date)} · day ${peak.horizon}`;
  byId('origin').textContent=`Forecast origin: ${day(record.forecast_origin)} · 56 daily observations`;
  byId('rows').replaceChildren();
  predictions.forEach((row,index)=>{const weather=record.weather_forecast[index];const tr=document.createElement('tr');[day(row.date),`D+${row.horizon}`,number(row.chronos2_mu),number(row.tcn_mu),number(row.ensemble_mu),`${weather.mean.toFixed(1)} / ${weather.max.toFixed(1)} / ${weather.min.toFixed(1)}`].forEach(value=>{const cell=document.createElement('td');cell.textContent=value;tr.append(cell);});byId('rows').append(tr);});
  const today=new Date().toLocaleDateString('en-CA',{timeZone:'Asia/Kolkata'});
  const age=Math.round((Date.parse(today)-Date.parse(record.forecast_origin))/86400000);
  const details=[['Demand coverage',`${day(record.forecast_origin)} · ${age} calendar day(s) behind today`],['Context window','56 consecutive days'],['Weather coverage',`${day(record.weather_forecast[0].date)} – ${day(record.weather_forecast.at(-1).date)}`],['Forecast issued',stamp(record.issued_at_utc)],['Inputs retrieved',stamp(record.inputs_fetched_at_utc)]];
  const dl=document.createElement('dl');details.forEach(([title,value])=>{const dt=document.createElement('dt');dt.textContent=title;const dd=document.createElement('dd');dd.textContent=value;dl.append(dt,dd);});byId('freshness').replaceChildren(dl);
  byId('status').className='';byId('status').textContent=`Saved forecast · issued ${stamp(record.issued_at_utc)}${age>2?' · Demand input is delayed; review input health.':''} · ${hostedMode?'Automatic refresh daily at 2:30 PM IST.':'Refresh to request a new forecast.'}`;
  chart();
}
async function request(url,options){const response=await fetch(url,options);const body=await response.json();if(!response.ok)throw new Error(body.error||'Request failed.');return body;}
byId('refresh').addEventListener('click',async()=>{const button=byId('refresh');button.disabled=true;button.textContent='Refreshing…';byId('status').textContent='Fetching demand and weather, then running the models. This may take several minutes.';try{render((await request('/api/refresh',{method:'POST',headers:{'X-GridPulse-Request':'dashboard'}})).forecast);await loadHistory();}catch(error){byId('status').className='error';byId('status').textContent=error.message;}finally{button.disabled=false;button.textContent='↻ Refresh forecast';}});
document.querySelectorAll('[data-range]').forEach(button=>button.addEventListener('click',()=>{historyDays=Number(button.dataset.range);document.querySelectorAll('[data-range]').forEach(item=>item.classList.toggle('selected',item===button));if(forecast)chart();}));
byId('components').addEventListener('change',()=>{if(forecast)chart();});
request('/api/dashboard').then(body=>render(body.forecast)).catch(()=>{byId('status').className='error';byId('status').textContent='The saved forecast could not be loaded. Refresh or restart the local server.';});

let historyRequest = 0;
async function loadHistory() {
  const currentRequest = ++historyRequest;
  try {
    const data = await request(`/api/history?horizon=${byId('history-horizon').value}`);
    if (currentRequest !== historyRequest) return;
    byId('history-rows').replaceChildren();
    data.rows.forEach(row => {
      const tr = document.createElement('tr');
      [day(row.date), row.predicted_mu === null ? 'No prior forecast' : number(row.predicted_mu), row.actual_mu === null ? 'Pending' : number(row.actual_mu), row.error_mu === null ? '—' : number(row.error_mu), row.horizon === null ? '—' : `D+${row.horizon}`, row.issued_at_utc ? stamp(row.issued_at_utc) : '—'].forEach(value => {
        const cell = document.createElement('td'); cell.textContent = value; tr.append(cell);
      });
      byId('history-rows').append(tr);
    });
    byId('history-status').textContent = `${data.archive_count} saved forecast(s) · Actuals retrieved: ${stamp(data.actuals_fetched_at_utc)} · Latest reported day: ${data.latest_actual_date ? day(data.latest_actual_date) : 'None'}`;
    if (data.latest_actual_date && data.latest_actual_date < data.rows.at(-1).date) {
      byId('history-status').textContent += ' · Newer actuals are not yet in the saved Grid-India reports.';
    }
    byId('history-metrics').textContent = data.scored_days ? `Observed 7-day MAE: ${number(data.mae_mu)} MU · ${data.scored_days}/7 matched days · This small live sample is separate from holdout MAE.` : '0/7 matched days · Live MAE will appear once prior forecasts and reported actuals overlap.';
    historyChart(data.rows);
  } catch (error) {
    if (currentRequest === historyRequest) byId('history-status').textContent = 'History could not be loaded. Restart the updated server and try again.';
  }
}
function historyChart(rows) {
  const values = rows.flatMap(row => [row.actual_mu, row.predicted_mu]).filter(value => value !== null);
  if (!values.length) { byId('history-chart').textContent = 'No observations or prior forecasts available for this window yet.'; return; }
  const minimum = Math.floor((Math.min(...values)-5)/10)*10;
  const maximum = Math.ceil((Math.max(...values)+5)/10)*10;
  const x = index => 55 + index*145;
  const y = value => 215-(value-minimum)/(maximum-minimum)*185;
  let svg = '<svg viewBox="0 0 1000 260" role="img" aria-label="Last seven completed days: archived predictions and actual energy met in million units">';
  for(let tick=0;tick<=4;tick++) { const value=minimum+(maximum-minimum)*tick/4; svg+=`<line x1="55" y1="${y(value)}" x2="950" y2="${y(value)}" stroke="#edf1eb"/><text x="40" y="${y(value)+4}" text-anchor="end" fill="#829188" font-size="10">${value.toFixed(0)}</text>`; }
  for (const [key,color] of [['actual_mu','#346c58'],['predicted_mu','#99ad4e']]) {
    let connected = false;
    let path = '';
    rows.forEach((row,index) => {
      if(row[key] === null) { connected=false; return; }
      path += `${connected?'L':'M'}${x(index)},${y(row[key])} `;
      connected=true;
      svg+=`<circle cx="${x(index)}" cy="${y(row[key])}" r="4" fill="${color}"><title>${day(row.date)} · ${key==='actual_mu'?'Actual':'Predicted'}: ${number(row[key])} MU</title></circle>`;
    });
    svg+=`<path d="${path}" fill="none" stroke="${color}" stroke-width="2" ${key==='predicted_mu'?'stroke-dasharray="5 4"':''}/>`;
  }
  rows.forEach((row,index)=>{svg+=`<text x="${x(index)}" y="245" text-anchor="middle" fill="#829188" font-size="11">${day(row.date)}</text>`;});
  byId('history-chart').innerHTML=svg+'</svg>';
}
async function syncActuals() {
  const button=byId('sync-actuals'); button.disabled=true; button.textContent='Updating…';
  let failure = false;
  try { await request('/api/actuals',{method:'POST',headers:{'X-GridPulse-Request':'dashboard'}}); }
  catch(error) { failure = true; }
  await loadHistory();
  if(failure) byId('history-status').textContent += ' · Actuals update unavailable; showing saved observations. Retry when connected.';
  button.disabled=false; button.textContent='↻ Update actuals';
}
byId('history-horizon').addEventListener('change',loadHistory);
byId('sync-actuals').addEventListener('click',syncActuals);
async function initializeHistory() {
  try {
    const config = await request('/api/config');
    if(config.hosted) {
      hostedMode=true;
      byId('status').textContent=byId('status').textContent.replace('Refresh to request a new forecast.', 'Automatic refresh daily at 2:30 PM IST.');
      byId('refresh').hidden=true;
      byId('sync-actuals').hidden=true;
      const note=document.createElement('p');
      note.textContent='Hosted dashboard · Automatic refresh daily at 2:30 PM IST. Reload the page to see the latest saved results.';
      byId('status').before(note);
      const historyNote=byId('track-record').lastElementChild;
      historyNote.textContent='Only forecasts saved before the target day began (IST) qualify. Missing actuals remain pending. Forecasts and actuals update automatically each day; no earlier predictions are backfilled.';
      await loadHistory();
      return;
    }
    await loadHistory();
    await syncActuals();
  } catch(error) {
    byId('history-status').textContent='Dashboard configuration could not be loaded. Reload the page to try again.';
  }
}
initializeHistory();
