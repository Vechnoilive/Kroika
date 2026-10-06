export interface AtlasLine {
  id: string;
  number: number;
  color: string;
  path: string;
  badge: [number, number];
  seated?: boolean;
}

const data: Array<[string, string, string, [number, number], boolean?]> = [
  ['height', '#334155', 'M95 25V950 M85 25H320 M85 950H320', [95, 80]],
  ['bust', '#bc3457', 'M230 280C245 268 390 268 409 280C390 302 245 302 230 280Z', [480, 280]],
  ['waist', '#c56b14', 'M247 360C260 345 377 345 390 360C377 377 260 377 247 360Z', [480, 360]],
  ['hips', '#087d68', 'M218 447C245 430 395 430 425 447C395 468 245 468 218 447Z', [480, 445]],
  ['neck_circumference', '#8b459c', 'M287 167C298 153 343 153 355 167C342 184 299 184 287 167Z', [480, 170]],
  ['chest_width', '#23749e', 'M242 247H397', [155, 247]],
  ['back_width', '#23749e', 'M673 240H863', [975, 240]],
  ['back_bust_arc', '#bc3457', 'M667 281Q768 317 866 281', [975, 300]],
  ['back_waist_arc', '#c56b14', 'M691 359Q768 389 841 359', [975, 375]],
  ['back_hip_arc', '#087d68', 'M665 447Q768 484 870 447', [975, 450]],
  ['shoulder_span', '#6260bb', 'M222 193H419', [155, 193]],
  ['shoulder_length', '#6260bb', 'M347 172L413 192', [480, 220]],
  ['back_neck_to_waist', '#b54977', 'M768 150V361', [570, 230]],
  ['front_neck_to_waist_over_bust', '#b54977', 'M350 174Q377 245 374 283Q365 329 364 362', [480, 405]],
  ['bust_path_height', '#ac491d', 'M413 193Q403 243 376 282', [480, 320]],
  ['bust_vertical_height', '#ac491d', 'M350 174V282H375', [155, 300]],
  ['bust_span', '#23749e', 'M275 285H370', [105, 335]],
  ['hip_depth', '#087d68', 'M1100 360V447 M1100 360H1174 M1100 447H1158', [1100, 405]],
  ['armscye_depth', '#ac491d', 'M1325 190V275 M1195 190H1325 M1290 275H1325', [1430, 230]],
  ['upper_arm_circumference', '#b03d42', 'M427 261Q444 250 457 266Q444 281 427 261Z', [525, 260]],
  ['wrist_circumference', '#b03d42', 'M464 478Q475 468 485 478Q479 491 464 478Z', [525, 485]],
  ['hand_circumference', '#b03d42', 'M466 520Q483 510 494 522Q483 536 466 520Z', [525, 545]],
  ['sleeve_length', '#5c6698', 'M213 195Q180 350 150 487', [155, 420]],
  ['elbow_circumference', '#b03d42', 'M182 346Q198 335 218 348Q203 365 182 346Z', [155, 370]],
  ['elbow_length', '#5c6698', 'M213 195Q191 285 198 346', [105, 280]],
  ['front_diagonal_shoulder_height', '#6260bb', 'M320 360L413 193', [480, 500]],
  ['back_diagonal_shoulder_height', '#6260bb', 'M768 361L866 190', [975, 515]],
  ['sitting_height', '#bf6a16', 'M330 450V642 M330 450H430 M330 642H450', [275, 535], true],
  ['crotch_length', '#9b4b88', 'M1259 365Q1250 488 1202 504Q1150 500 1163 366', [1430, 425]],
  ['outside_leg_length', '#2b7b88', 'M1368 360V949 M1280 360H1368 M1297 949H1368', [1430, 545]],
  ['inseam_length', '#2b7b88', 'M319 505L316 945', [480, 620]],
  ['thigh_circumference', '#31816f', 'M226 542Q270 523 315 542Q272 565 226 542Z', [155, 555]],
  ['knee_circumference', '#31816f', 'M241 680Q270 664 302 680Q272 695 241 680Z', [155, 680]],
  ['trouser_hem_circumference', '#31816f', 'M242 918Q270 900 300 918Q270 934 242 918Z', [155, 875]],
  ['knee_height', '#2b7b88', 'M1100 680V949 M1100 680H1190 M1100 949H1200', [1100, 820]],
  ['shoulder_slope', '#6260bb', 'M350 172H415 M350 172L413 192 M385 172Q385 180 383 183', [480, 115]],
  ['hip_inclination', '#087d68', 'M690 359V447 M690 359L665 447 M690 390Q683 390 681 391', [570, 400]],
];

export const ATLAS_LINES: AtlasLine[] = data.map(([id, color, path, badge, seated], index) => ({
  id, color, path, badge, seated, number: index + 1,
}));
export const ATLAS_BY_ID = new Map(ATLAS_LINES.map((line) => [line.id, line]));
